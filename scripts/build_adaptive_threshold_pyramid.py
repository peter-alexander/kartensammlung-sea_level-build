#!/usr/bin/env python3

import argparse
import io
import json
import math
import shutil
import sqlite3
from collections import OrderedDict, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image


TERRARIUM_OFFSET = 32768.0
TERRARIUM_SCALE = 256.0
TERRARIUM_MAX_RAW = 256 * 256 * 256 - 1


def parse_levels(levels_csv):
	levels = [
		float(value)
		for value in str(levels_csv).split(",")
		if str(value).strip()
	]
	if not levels:
		raise ValueError("Threshold-Level dürfen nicht leer sein.")
	if any(not math.isfinite(value) for value in levels):
		raise ValueError("Threshold-Level müssen endlich sein.")
	if any(b <= a for a, b in zip(levels, levels[1:])):
		raise ValueError("Threshold-Level müssen streng aufsteigend sein.")
	return levels


def encode_terrarium(values):
	array = np.asarray(values, dtype=np.float64)
	if not np.all(np.isfinite(array)):
		raise ValueError("Threshold-Raster enthält nicht-endliche Werte.")

	raw = np.rint(
		(array + TERRARIUM_OFFSET) * TERRARIUM_SCALE
	).astype(np.int64)
	raw = np.clip(raw, 0, TERRARIUM_MAX_RAW)

	red = ((raw >> 16) & 255).astype(np.uint8)
	green = ((raw >> 8) & 255).astype(np.uint8)
	blue = (raw & 255).astype(np.uint8)
	return np.stack((red, green, blue), axis=-1)


def class_lookup(levels, sentinel):
	if int(sentinel) != len(levels):
		raise ValueError(
			"sentinel_class muss exakt der Anzahl Threshold-Level entsprechen."
		)
	last = float(levels[-1])
	sentinel_m = last + 1.0
	return np.asarray((*levels, sentinel_m), dtype=np.float64), sentinel_m


def png_bytes(classes, lookup, sentinel):
	array = np.asarray(classes, dtype=np.uint8)
	if array.size and int(np.max(array)) > int(sentinel):
		raise ValueError("Threshold-Raster enthält ungültige Klassen.")
	rgb = encode_terrarium(lookup[array])
	buffer = io.BytesIO()
	Image.fromarray(rgb, "RGB").save(
		buffer,
		format="PNG",
		optimize=False,
		compress_level=6,
	)
	return buffer.getvalue()


def downsample_bayer(array):
	height, width = array.shape
	if height % 2 != 0 or width % 2 != 0:
		raise ValueError(
			f"Rastergröße {width}x{height} ist für 2x-Downsampling nicht gerade."
		)

	a00 = array[0::2, 0::2]
	a01 = array[0::2, 1::2]
	a10 = array[1::2, 0::2]
	a11 = array[1::2, 1::2]
	out_height, out_width = a00.shape
	output = np.empty((out_height, out_width), dtype=np.uint8)
	output[0::2, 0::2] = a00[0::2, 0::2]
	output[0::2, 1::2] = a01[0::2, 1::2]
	output[1::2, 0::2] = a10[1::2, 0::2]
	output[1::2, 1::2] = a11[1::2, 1::2]
	return output


def pixel_to_lonlat(x, y, zoom, tile_size):
	world = float((1 << int(zoom)) * int(tile_size))
	lon = float(x) / world * 360.0 - 180.0
	n = math.pi * (1.0 - 2.0 * float(y) / world)
	lat = math.degrees(math.atan(math.sinh(n)))
	return lon, lat


def domain_bounds(domains, zoom, tile_size):
	if not domains:
		return None
	x0 = min(int(domain["global_pixel_x0"]) for domain in domains)
	y0 = min(int(domain["global_pixel_y0"]) for domain in domains)
	x1 = max(int(domain["global_pixel_x1"]) for domain in domains)
	y1 = max(int(domain["global_pixel_y1"]) for domain in domains)
	west, north = pixel_to_lonlat(x0, y0, zoom, tile_size)
	east, south = pixel_to_lonlat(x1, y1, zoom, tile_size)
	return [west, south, east, north]


def init_mbtiles(path, metadata):
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)
	if path.exists():
		path.unlink()

	db = sqlite3.connect(path)
	db.execute("PRAGMA journal_mode=OFF")
	db.execute("PRAGMA synchronous=OFF")
	db.execute("PRAGMA temp_store=MEMORY")
	db.execute(
		"CREATE TABLE metadata (name TEXT, value TEXT)"
	)
	db.execute(
		"""
		CREATE TABLE tiles (
			zoom_level INTEGER,
			tile_column INTEGER,
			tile_row INTEGER,
			tile_data BLOB
		)
		"""
	)
	db.execute(
		"""
		CREATE UNIQUE INDEX tile_index
		ON tiles (zoom_level, tile_column, tile_row)
		"""
	)
	db.executemany(
		"INSERT INTO metadata (name, value) VALUES (?, ?)",
		[(str(key), str(value)) for key, value in metadata.items()],
	)
	db.commit()
	return db


def set_metadata(db, key, value):
	db.execute("DELETE FROM metadata WHERE name = ?", (str(key),))
	db.execute(
		"INSERT INTO metadata (name, value) VALUES (?, ?)",
		(str(key), str(value)),
	)


def insert_tile(db, zoom, x, y, data):
	tms_y = (1 << int(zoom)) - 1 - int(y)
	db.execute(
		"""
		INSERT INTO tiles (
			zoom_level,
			tile_column,
			tile_row,
			tile_data
		) VALUES (?, ?, ?, ?)
		""",
		(int(zoom), int(x), tms_y, sqlite3.Binary(data)),
	)


def raw_tile_path(root, zoom, x, y):
	return Path(root) / f"z{int(zoom)}" / f"{int(x)}-{int(y)}.u8"


def write_raw_tile(root, zoom, x, y, tile):
	path = raw_tile_path(root, zoom, x, y)
	path.parent.mkdir(parents=True, exist_ok=True)
	tile.tofile(path)


def read_raw_tile(root, zoom, x, y, tile_size):
	path = raw_tile_path(root, zoom, x, y)
	return np.fromfile(path, dtype=np.uint8).reshape(
		(int(tile_size), int(tile_size))
	)


class DomainCache:
	def __init__(self, threshold_dir, domains, max_bytes=1024 ** 3):
		self.threshold_dir = Path(threshold_dir)
		self.domains = domains
		self.max_bytes = max(1, int(max_bytes))
		self.cache = OrderedDict()
		self.cache_bytes = 0

	def validate_files(self):
		for index, domain in enumerate(self.domains):
			path = self.threshold_dir / domain["file"]
			expected = int(domain["width"]) * int(domain["height"])
			if not path.exists():
				raise FileNotFoundError(path)
			if path.stat().st_size != expected:
				raise ValueError(
					f"Falsche Threshold-Größe für Domain {domain['id']}: "
					f"{path.stat().st_size} != {expected}."
				)
			if index and index % 5000 == 0:
				print(f"  {index} Domain-Dateien geprüft")

	def get(self, index):
		index = int(index)
		if index in self.cache:
			array = self.cache.pop(index)
			self.cache[index] = array
			return array

		domain = self.domains[index]
		path = self.threshold_dir / domain["file"]
		array = np.fromfile(
			path,
			dtype=np.uint8,
		).reshape((int(domain["height"]), int(domain["width"])))
		self.cache[index] = array
		self.cache_bytes += int(array.nbytes)
		while self.cache_bytes > self.max_bytes and len(self.cache) > 1:
			_, old = self.cache.popitem(last=False)
			self.cache_bytes -= int(old.nbytes)
		return array

	def close(self):
		self.cache.clear()
		self.cache_bytes = 0


def native_tile_jobs(domains, tile_size):
	jobs = defaultdict(list)
	for index, domain in enumerate(domains):
		x0 = int(domain["global_pixel_x0"])
		y0 = int(domain["global_pixel_y0"])
		x1 = int(domain["global_pixel_x1"])
		y1 = int(domain["global_pixel_y1"])
		width = int(domain["width"])
		height = int(domain["height"])
		if x1 - x0 != width or y1 - y0 != height:
			raise ValueError(
				f"Inkonsistente Pixelgeometrie für Domain {domain['id']}."
			)

		for tile_y in range(y0 // tile_size, (y1 - 1) // tile_size + 1):
			for tile_x in range(x0 // tile_size, (x1 - 1) // tile_size + 1):
				tile_x0 = tile_x * tile_size
				tile_y0 = tile_y * tile_size
				overlap_x0 = max(x0, tile_x0)
				overlap_y0 = max(y0, tile_y0)
				overlap_x1 = min(x1, tile_x0 + tile_size)
				overlap_y1 = min(y1, tile_y0 + tile_size)
				jobs[(tile_x, tile_y)].append((
					index,
					overlap_x0 - x0,
					overlap_y0 - y0,
					overlap_x1 - x0,
					overlap_y1 - y0,
					overlap_x0 - tile_x0,
					overlap_y0 - tile_y0,
					overlap_x1 - tile_x0,
					overlap_y1 - tile_y0,
				))
	return jobs


def build_native_zoom(
	db,
	domains,
	threshold_dir,
	raw_root,
	*,
	zoom,
	tile_size,
	sentinel,
	lookup,
	cache_mib,
):
	jobs = native_tile_jobs(domains, tile_size)
	reader = DomainCache(
		threshold_dir,
		domains,
		max_bytes=int(cache_mib) * 1024 * 1024,
	)
	reader.validate_files()

	coords = set()
	png_total = 0
	all_sentinel_tiles = 0
	covered_pixels = 0
	try:
		for number, ((tile_x, tile_y), pieces) in enumerate(
			sorted(jobs.items()),
			start=1,
		):
			tile = np.full(
				(tile_size, tile_size),
				sentinel,
				dtype=np.uint8,
			)
			occupied = np.zeros(
				(tile_size, tile_size),
				dtype=bool,
			)

			for (
				index,
				sx0,
				sy0,
				sx1,
				sy1,
				dx0,
				dy0,
				dx1,
				dy1,
			) in pieces:
				target_occupied = occupied[dy0:dy1, dx0:dx1]
				if np.any(target_occupied):
					raise AssertionError(
						f"Überlappende Domains in Z{zoom}-Tile {tile_x}/{tile_y}."
					)
				values = reader.get(index)[sy0:sy1, sx0:sx1]
				if values.size and int(np.max(values)) > sentinel:
					raise ValueError(
						f"Domain {domains[index]['id']} enthält ungültige "
						f"Threshold-Klasse {int(np.max(values))}."
					)
				tile[dy0:dy1, dx0:dx1] = values
				target_occupied[:] = True
				covered_pixels += int(values.size)

			if np.all(tile == sentinel):
				all_sentinel_tiles += 1
				continue

			data = png_bytes(tile, lookup, sentinel)
			insert_tile(db, zoom, tile_x, tile_y, data)
			png_total += len(data)
			coords.add((tile_x, tile_y))
			write_raw_tile(raw_root, zoom, tile_x, tile_y, tile)

			if number % 500 == 0:
				db.commit()
				print(
					f"  Z{zoom}: {number}/{len(jobs)} native Tiles verarbeitet; "
					f"{len(coords)} nicht leer"
				)
	finally:
		reader.close()

	db.commit()
	return coords, {
		"zoom": int(zoom),
		"candidate_tiles": len(jobs),
		"tiles": len(coords),
		"all_sentinel_tiles": all_sentinel_tiles,
		"png_bytes": int(png_total),
		"covered_domain_pixels": int(covered_pixels),
	}


def build_parent_zoom(
	db,
	raw_root,
	child_coords,
	*,
	child_zoom,
	tile_size,
	sentinel,
	lookup,
	keep_raw,
):
	parent_zoom = int(child_zoom) - 1
	parent_candidates = sorted({
		(int(x) // 2, int(y) // 2)
		for x, y in child_coords
	})
	parent_coords = set()
	png_total = 0
	all_sentinel_tiles = 0

	for number, (parent_x, parent_y) in enumerate(
		parent_candidates,
		start=1,
	):
		mosaic = np.full(
			(tile_size * 2, tile_size * 2),
			sentinel,
			dtype=np.uint8,
		)
		for dy in (0, 1):
			for dx in (0, 1):
				child = (parent_x * 2 + dx, parent_y * 2 + dy)
				if child not in child_coords:
					continue
				values = read_raw_tile(
					raw_root,
					child_zoom,
					child[0],
					child[1],
					tile_size,
				)
				mosaic[
					dy * tile_size:(dy + 1) * tile_size,
					dx * tile_size:(dx + 1) * tile_size,
				] = values

		parent = downsample_bayer(mosaic)
		if np.all(parent == sentinel):
			all_sentinel_tiles += 1
			continue

		data = png_bytes(parent, lookup, sentinel)
		insert_tile(db, parent_zoom, parent_x, parent_y, data)
		png_total += len(data)
		parent_coords.add((parent_x, parent_y))
		if keep_raw:
			write_raw_tile(
				raw_root,
				parent_zoom,
				parent_x,
				parent_y,
				parent,
			)

		if number % 500 == 0:
			db.commit()

	db.commit()
	shutil.rmtree(
		Path(raw_root) / f"z{int(child_zoom)}",
		ignore_errors=True,
	)
	return parent_coords, {
		"zoom": parent_zoom,
		"candidate_tiles": len(parent_candidates),
		"tiles": len(parent_coords),
		"all_sentinel_tiles": all_sentinel_tiles,
		"png_bytes": int(png_total),
	}


def convert_pmtiles(mbtiles_path, pmtiles_path):
	try:
		from pmtiles.convert import mbtiles_to_pmtiles
	except ImportError as error:
		raise RuntimeError(
			"PMTiles-Ausgabe benötigt das Python-Paket 'pmtiles'."
		) from error

	pmtiles_path = Path(pmtiles_path)
	if pmtiles_path.exists():
		pmtiles_path.unlink()
	mbtiles_to_pmtiles(
		str(mbtiles_path),
		str(pmtiles_path),
		None,
	)
	return pmtiles_path.stat().st_size


def tier_metadata(component_id, zoom, minzoom, bounds, tile_size):
	return {
		"name": f"Sea-level threshold component {component_id} Z{zoom}",
		"type": "overlay",
		"version": "1",
		"description": (
			"Adaptive terrain-based sea-level inundation threshold; "
			f"native tier Z{zoom}"
		),
		"format": "png",
		"bounds": ",".join(f"{value:.10f}" for value in bounds),
		"minzoom": int(minzoom),
		"maxzoom": int(zoom),
		"tile_size": int(tile_size),
		"encoding": "terrarium",
		"attribution": (
			"DEM: Mapterhorn; coastline/ocean: OpenStreetMap contributors"
		),
	}


def build_tier(
	manifest,
	domains,
	threshold_dir,
	output_dir,
	work_dir,
	*,
	native_zoom,
	minzoom,
	lookup,
	sentinel,
	cache_mib,
	make_pmtiles,
	keep_mbtiles,
):
	tile_size = int(manifest["tile_size"])
	component_id = int(manifest["component_id"])
	bounds = domain_bounds(domains, native_zoom, tile_size)
	if bounds is None:
		raise ValueError(f"Z{native_zoom} enthält keine Domains.")

	output_dir = Path(output_dir)
	work_dir = Path(work_dir) / f"z{native_zoom}"
	shutil.rmtree(work_dir, ignore_errors=True)
	work_dir.mkdir(parents=True, exist_ok=True)
	raw_root = work_dir / "raw"

	mbtiles_path = output_dir / (
		f"sea-level-threshold-component-{component_id}-z{native_zoom}.mbtiles"
	)
	metadata = tier_metadata(
		component_id,
		native_zoom,
		minzoom,
		bounds,
		tile_size,
	)
	db = init_mbtiles(mbtiles_path, metadata)

	zoom_reports = []
	try:
		coords, report = build_native_zoom(
			db,
			domains,
			threshold_dir,
			raw_root,
			zoom=native_zoom,
			tile_size=tile_size,
			sentinel=sentinel,
			lookup=lookup,
			cache_mib=cache_mib,
		)
		zoom_reports.append(report)

		for child_zoom in range(native_zoom, minzoom, -1):
			if not coords:
				break
			coords, report = build_parent_zoom(
				db,
				raw_root,
				coords,
				child_zoom=child_zoom,
				tile_size=tile_size,
				sentinel=sentinel,
				lookup=lookup,
				keep_raw=(child_zoom - 1 > minzoom),
			)
			zoom_reports.append(report)
			print(
				f"  Z{report['zoom']}: {report['tiles']} Tiles, "
				f"{report['png_bytes'] / (1024 ** 2):.2f} MiB PNG"
			)

		populated = [
			item["zoom"]
			for item in zoom_reports
			if item["tiles"] > 0
		]
		if not populated:
			raise RuntimeError(
				f"Z{native_zoom}-Tier enthält ausschließlich Sentinel-Werte."
			)
		actual_minzoom = min(populated)
		set_metadata(db, "minzoom", actual_minzoom)
		set_metadata(db, "maxzoom", native_zoom)
		db.commit()
	finally:
		db.close()
		shutil.rmtree(work_dir, ignore_errors=True)

	pmtiles_path = None
	pmtiles_bytes = None
	if make_pmtiles:
		pmtiles_path = mbtiles_path.with_suffix(".pmtiles")
		pmtiles_bytes = convert_pmtiles(
			mbtiles_path,
			pmtiles_path,
		)

	mbtiles_bytes = mbtiles_path.stat().st_size
	if make_pmtiles and not keep_mbtiles:
		mbtiles_path.unlink()
		mbtiles_output = None
	else:
		mbtiles_output = str(mbtiles_path)

	return {
		"native_zoom": int(native_zoom),
		"minzoom": int(actual_minzoom),
		"maxzoom": int(native_zoom),
		"domain_count": len(domains),
		"native_input_cells": int(sum(
			int(domain["width"]) * int(domain["height"])
			for domain in domains
		)),
		"bounds": bounds,
		"zooms": zoom_reports,
		"tile_count": int(sum(item["tiles"] for item in zoom_reports)),
		"png_bytes": int(sum(item["png_bytes"] for item in zoom_reports)),
		"mbtiles": mbtiles_output,
		"mbtiles_bytes": int(mbtiles_bytes),
		"pmtiles": str(pmtiles_path) if pmtiles_path is not None else None,
		"pmtiles_bytes": int(pmtiles_bytes) if pmtiles_bytes is not None else None,
	}


def build_adaptive_threshold_pyramids(
	manifest_path,
	threshold_dir,
	output_dir,
	work_dir,
	*,
	minzoom=5,
	cache_mib=1024,
	make_pmtiles=False,
	keep_mbtiles=True,
):
	manifest = json.loads(
		Path(manifest_path).read_text(encoding="utf-8")
	)
	if int(manifest.get("schema_version", 0)) != 1:
		raise ValueError("Unbekannte Reconstruction-Manifest-Version.")
	if int(manifest.get("domain_count", -1)) != len(manifest["domains"]):
		raise ValueError("domain_count stimmt nicht mit domains überein.")

	tile_size = int(manifest["tile_size"])
	if tile_size <= 0 or tile_size % 2:
		raise ValueError("tile_size muss positiv und gerade sein.")

	parent_zoom = int(manifest["parent_zoom"])
	minzoom = int(minzoom)
	if minzoom < 0 or minzoom > parent_zoom:
		raise ValueError(
			"minzoom muss zwischen 0 und parent_zoom liegen."
		)

	sentinel = int(manifest["sentinel_class"])
	levels = parse_levels(manifest["levels"])
	lookup, sentinel_m = class_lookup(levels, sentinel)

	domains_by_zoom = defaultdict(list)
	seen_ids = set()
	for domain in manifest["domains"]:
		domain = dict(domain)
		domain_id = int(domain["id"])
		if domain_id in seen_ids:
			raise ValueError(f"Doppelte Domain-ID {domain_id}.")
		seen_ids.add(domain_id)
		zoom = int(domain["zoom"])
		if zoom < parent_zoom:
			raise ValueError(
				f"Domain {domain_id} liegt unter parent_zoom."
			)
		domains_by_zoom[zoom].append(domain)

	output_dir = Path(output_dir)
	output_dir.mkdir(parents=True, exist_ok=True)
	work_dir = Path(work_dir)
	shutil.rmtree(work_dir, ignore_errors=True)
	work_dir.mkdir(parents=True, exist_ok=True)

	tiers = []
	for zoom in sorted(domains_by_zoom):
		print(
			f"Baue adaptiven Threshold-Tier Z{zoom}: "
			f"{len(domains_by_zoom[zoom])} Domains"
		)
		tiers.append(build_tier(
			manifest,
			domains_by_zoom[zoom],
			threshold_dir,
			output_dir,
			work_dir,
			native_zoom=zoom,
			minzoom=minzoom,
			lookup=lookup,
			sentinel=sentinel,
			cache_mib=cache_mib,
			make_pmtiles=make_pmtiles,
			keep_mbtiles=keep_mbtiles,
		))

	shutil.rmtree(work_dir, ignore_errors=True)
	report = {
		"schema_version": 1,
		"method": "adaptive-native-tier-pyramids-v1",
		"component_id": int(manifest["component_id"]),
		"parent_zoom": parent_zoom,
		"tile_size": tile_size,
		"sentinel_class": sentinel,
		"sentinel_m": sentinel_m,
		"levels": manifest["levels"],
		"requested_minzoom": minzoom,
		"tier_count": len(tiers),
		"native_zooms": [item["native_zoom"] for item in tiers],
		"domain_count": len(manifest["domains"]),
		"native_input_cells": int(sum(
			item["native_input_cells"]
			for item in tiers
		)),
		"tile_count": int(sum(item["tile_count"] for item in tiers)),
		"png_bytes": int(sum(item["png_bytes"] for item in tiers)),
		"tiers": tiers,
		"maplibre": {
			"composition": "stacked-native-tiers",
			"layer_order": [item["native_zoom"] for item in tiers],
			"note": (
				"Jeder Tier ist eine eigene raster-dem-Source mit seinem nativen "
				"maxzoom. Dadurch kann MapLibre niedrigere Tiers regulär overzoomen; "
				f"Sentinel {sentinel_m:g} m liegt oberhalb des darstellbaren "
				"Threshold-Bereichs."
			),
			"sources": [
				{
					"id": f"sea_level_threshold_z{item['native_zoom']}",
					"type": "raster-dem",
					"tileSize": tile_size,
					"minzoom": item["minzoom"],
					"maxzoom": item["maxzoom"],
					"encoding": "terrarium",
					"archive": (
						item["pmtiles"]
						if item["pmtiles"] is not None
						else item["mbtiles"]
					),
				}
				for item in tiers
			],
		},
	}

	report_path = output_dir / "adaptive-threshold-pyramid-report.json"
	report_path.write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)
	return report


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Erzeugt aus einem adaptiven Threshold-Reconstruction-Manifest "
			"pro nativer Auflösungsstufe eine Terrarium-Rasterpyramide."
		)
	)
	parser.add_argument("--manifest", required=True)
	parser.add_argument("--threshold-dir", required=True)
	parser.add_argument("--output-dir", required=True)
	parser.add_argument("--work-dir", required=True)
	parser.add_argument("--minzoom", type=int, default=5)
	parser.add_argument("--cache-mib", type=int, default=1024)
	parser.add_argument(
		"--pmtiles",
		action="store_true",
		help="Konvertiert jeden fertigen MBTiles-Tier zusätzlich nach PMTiles.",
	)
	parser.add_argument(
		"--delete-mbtiles",
		action="store_true",
		help="Löscht MBTiles nach erfolgreicher PMTiles-Konvertierung.",
	)
	args = parser.parse_args()

	if args.delete_mbtiles and not args.pmtiles:
		parser.error("--delete-mbtiles benötigt --pmtiles.")

	report = build_adaptive_threshold_pyramids(
		args.manifest,
		args.threshold_dir,
		args.output_dir,
		args.work_dir,
		minzoom=args.minzoom,
		cache_mib=args.cache_mib,
		make_pmtiles=args.pmtiles,
		keep_mbtiles=not args.delete_mbtiles,
	)
	print(json.dumps({
		"component_id": report["component_id"],
		"tier_count": report["tier_count"],
		"native_zooms": report["native_zooms"],
		"tile_count": report["tile_count"],
		"png_bytes": report["png_bytes"],
	}, indent=2))


if __name__ == "__main__":
	main()
