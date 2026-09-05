#!/usr/bin/env python3

import io
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_adaptive_threshold_pyramid import (
	build_adaptive_threshold_pyramids,
	downsample_bayer,
)


TERRARIUM_OFFSET = 32768.0


def decode_png(data):
	rgb = np.asarray(
		Image.open(io.BytesIO(data)).convert("RGB"),
		dtype=np.float64,
	)
	return (
		rgb[:, :, 0] * 256.0
		+ rgb[:, :, 1]
		+ rgb[:, :, 2] / 256.0
		- TERRARIUM_OFFSET
	)


def read_tile(path, zoom, x, y):
	db = sqlite3.connect(path)
	try:
		tms_y = (1 << int(zoom)) - 1 - int(y)
		row = db.execute(
			"""
			SELECT tile_data
			FROM tiles
			WHERE zoom_level = ?
			AND tile_column = ?
			AND tile_row = ?
			""",
			(int(zoom), int(x), int(tms_y)),
		).fetchone()
		return None if row is None else decode_png(row[0])
	finally:
		db.close()


def main():
	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		threshold_dir = tmp / "thresholds"
		threshold_dir.mkdir()
		output_dir = tmp / "output"
		work_dir = tmp / "work"

		west = np.asarray([
			[0, 0, 1, 1],
			[0, 0, 1, 1],
			[2, 2, 3, 3],
			[2, 2, 3, 3],
		], dtype=np.uint8)
		east = np.asarray([
			[2, 2, 2, 2],
			[2, 2, 2, 2],
			[1, 1, 1, 1],
			[1, 1, 1, 1],
		], dtype=np.uint8)
		west.tofile(threshold_dir / "r1-c1.u8")
		east.tofile(threshold_dir / "r2-c2.u8")

		manifest = {
			"schema_version": 1,
			"component_id": 1,
			"parent_zoom": 1,
			"coarse_factor": 2,
			"tile_size": 4,
			"sentinel_class": 3,
			"levels": "0,1,2",
			"domain_count": 2,
			"domains": [
				{
					"id": 1,
					"zoom": 1,
					"file": "r1-c1.u8",
					"global_pixel_x0": 0,
					"global_pixel_y0": 0,
					"width": 4,
					"height": 4,
					"global_pixel_x1": 4,
					"global_pixel_y1": 4,
					"coarse_x0": 0,
					"coarse_y0": 0,
					"coarse_width": 2,
					"coarse_height": 2,
				},
				{
					"id": 2,
					"zoom": 2,
					"file": "r2-c2.u8",
					"global_pixel_x0": 8,
					"global_pixel_y0": 0,
					"width": 4,
					"height": 4,
					"global_pixel_x1": 12,
					"global_pixel_y1": 4,
					"coarse_x0": 2,
					"coarse_y0": 0,
					"coarse_width": 1,
					"coarse_height": 1,
				},
			],
		}
		manifest_path = tmp / "manifest.json"
		manifest_path.write_text(
			json.dumps(manifest),
			encoding="utf-8",
		)

		report = build_adaptive_threshold_pyramids(
			manifest_path,
			threshold_dir,
			output_dir,
			work_dir,
			minzoom=0,
			cache_mib=16,
			make_pmtiles=True,
			keep_mbtiles=True,
		)
		if report["native_zooms"] != [1, 2]:
			raise AssertionError(report)
		if report["tier_count"] != 2:
			raise AssertionError(report)
		if report["tile_count"] != 5:
			raise AssertionError(report)

		z1 = output_dir / "sea-level-threshold-component-1-z1.mbtiles"
		z2 = output_dir / "sea-level-threshold-component-1-z2.mbtiles"
		for path in (z1, z2):
			if not path.exists():
				raise AssertionError(path)
			pmtiles = path.with_suffix(".pmtiles")
			if not pmtiles.exists() or pmtiles.stat().st_size <= 127:
				raise AssertionError(pmtiles)

		native = read_tile(z1, 1, 0, 0)
		if native is None:
			raise AssertionError("Z1-Nativtile fehlt.")
		expected_native = np.asarray([
			[0.0, 0.0, 1.0, 1.0],
			[0.0, 0.0, 1.0, 1.0],
			[2.0, 2.0, 3.0, 3.0],
			[2.0, 2.0, 3.0, 3.0],
		])
		if not np.array_equal(native, expected_native):
			raise AssertionError(native)

		mosaic = np.full((8, 8), 3, dtype=np.uint8)
		mosaic[0:4, 0:4] = west
		expected_parent_classes = downsample_bayer(mosaic)
		expected_parent = np.asarray(
			[0.0, 1.0, 2.0, 3.0],
		)[expected_parent_classes]
		parent = read_tile(z1, 0, 0, 0)
		if not np.array_equal(parent, expected_parent):
			raise AssertionError({
				"actual": parent.tolist(),
				"expected": expected_parent.tolist(),
			})

		left_parent = read_tile(z1, 0, 0, 0)
		right_parent = read_tile(z2, 0, 0, 0)
		valid_sources = (
			(left_parent < 3.0).astype(np.uint8)
			+ (right_parent < 3.0).astype(np.uint8)
		)
		if np.any(valid_sources > 1):
			raise AssertionError(valid_sources)

		overlap_manifest = dict(manifest)
		overlap_manifest["domains"] = [
			dict(manifest["domains"][0]),
			{
				**manifest["domains"][0],
				"id": 3,
				"file": "r3-c1.u8",
			},
		]
		overlap_manifest["domain_count"] = 2
		np.full((4, 4), 3, dtype=np.uint8).tofile(
			threshold_dir / "r3-c1.u8"
		)
		overlap_path = tmp / "overlap.json"
		overlap_path.write_text(
			json.dumps(overlap_manifest),
			encoding="utf-8",
		)
		raised = False
		try:
			build_adaptive_threshold_pyramids(
				overlap_path,
				threshold_dir,
				tmp / "overlap-output",
				tmp / "overlap-work",
				minzoom=0,
				cache_mib=16,
			)
		except AssertionError as error:
			if "Überlappende Domains" not in str(error):
				raise
			raised = True
		if not raised:
			raise AssertionError(
				"Überlappende native Domains wurden nicht erkannt."
			)

	print("ok")


if __name__ == "__main__":
	main()
