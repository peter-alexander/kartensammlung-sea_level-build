#!/usr/bin/env python3

import argparse
import json
from collections import Counter
from pathlib import Path

import fiona
import numpy as np
from affine import Affine
from rasterio.features import rasterize


def select_seed_domains(
	domains,
	sea_mask,
	*,
	mask_origin_x,
	mask_origin_y,
	halo_coarse_cells=1,
):
	sea_mask = np.asarray(
		sea_mask,
		dtype=np.uint8,
	)
	halo = int(halo_coarse_cells)
	if halo < 0:
		raise ValueError(
			"halo_coarse_cells muss >= 0 sein."
		)

	height, width = sea_mask.shape
	selected = []

	for index, domain in enumerate(domains, start=1):
		x0 = (
			int(domain["coarse_x0"])
			- int(mask_origin_x)
		)
		y0 = (
			int(domain["coarse_y0"])
			- int(mask_origin_y)
		)
		x1 = x0 + int(domain["coarse_width"])
		y1 = y0 + int(domain["coarse_height"])

		sx0 = max(0, x0 - halo)
		sy0 = max(0, y0 - halo)
		sx1 = min(width, x1 + halo)
		sy1 = min(height, y1 + halo)

		if (
			sx1 > sx0
			and sy1 > sy0
			and np.any(
				sea_mask[sy0:sy1, sx0:sx1] != 0
			)
		):
			selected.append(
				int(domain.get("id", index))
			)

	return selected


def rasterize_coarse_sea(
	domains,
	parent_grid,
	sea_vector_path,
	*,
	coarse_factor,
	halo_coarse_cells=1,
):
	factor = int(coarse_factor)
	halo = int(halo_coarse_cells)
	if factor <= 0:
		raise ValueError("coarse_factor muss > 0 sein.")
	if not domains:
		raise ValueError("Keine adaptiven Domains.")

	coarse_width = int(parent_grid["width"]) // factor
	coarse_height = int(parent_grid["height"]) // factor
	min_x = max(
		0,
		min(
			int(domain["coarse_x0"])
			for domain in domains
		) - halo,
	)
	min_y = max(
		0,
		min(
			int(domain["coarse_y0"])
			for domain in domains
		) - halo,
	)
	max_x = min(
		coarse_width,
		max(
			int(domain["coarse_x0"])
			+ int(domain["coarse_width"])
			for domain in domains
		) + halo,
	)
	max_y = min(
		coarse_height,
		max(
			int(domain["coarse_y0"])
			+ int(domain["coarse_height"])
			for domain in domains
		) + halo,
	)

	width = max_x - min_x
	height = max_y - min_y
	if width <= 0 or height <= 0:
		raise ValueError(
			"Ungültiges grobes Sea-Seed-Fenster."
		)

	resolution = (
		float(parent_grid["resolution"])
		* factor
	)
	left = (
		float(parent_grid["left"])
		+ min_x * resolution
	)
	top = (
		float(parent_grid["top"])
		- min_y * resolution
	)
	right = left + width * resolution
	bottom = top - height * resolution

	with fiona.open(sea_vector_path) as source:
		geometries = [
			feature["geometry"]
			for feature in source.filter(
				bbox=(left, bottom, right, top)
			)
			if feature["geometry"] is not None
		]

	transform = Affine(
		resolution,
		0.0,
		left,
		0.0,
		-resolution,
		top,
	)
	sea = rasterize(
		(
			(geometry, 1)
			for geometry in geometries
		),
		out_shape=(height, width),
		fill=0,
		transform=transform,
		all_touched=True,
		dtype=np.uint8,
	)

	return {
		"sea_mask": sea,
		"origin_x": min_x,
		"origin_y": min_y,
		"width": width,
		"height": height,
		"sea_cells": int(
			np.count_nonzero(sea)
		),
		"geometry_count": len(geometries),
		"bounds": [
			left,
			bottom,
			right,
			top,
		],
	}


def plan_seed_domains(
	adaptive_plan,
	parent_grid,
	sea_vector_path,
	*,
	coarse_factor,
	halo_coarse_cells=1,
):
	domains = [
		{
			**domain,
			"id": int(domain.get("id", index)),
		}
		for index, domain in enumerate(
			adaptive_plan["domains"],
			start=1,
		)
	]

	raster = rasterize_coarse_sea(
		domains,
		parent_grid,
		sea_vector_path,
		coarse_factor=coarse_factor,
		halo_coarse_cells=halo_coarse_cells,
	)
	ids = select_seed_domains(
		domains,
		raster["sea_mask"],
		mask_origin_x=raster["origin_x"],
		mask_origin_y=raster["origin_y"],
		halo_coarse_cells=halo_coarse_cells,
	)

	by_id = {
		int(domain["id"]): domain
		for domain in domains
	}
	zoom_counts = Counter(
		int(by_id[domain_id]["zoom"])
		for domain_id in ids
	)

	return {
		"schema_version": 1,
		"strategy": (
			"coarse all-touched sea raster with a conservative "
			"coarse-cell halo; false positives only affect "
			"performance, while non-seed domains are activated "
			"later by boundary improvements"
		),
		"domain_count": len(
			adaptive_plan["domains"]
		),
		"seed_domain_count": len(ids),
		"seed_domain_fraction": (
			len(ids)
			/ len(adaptive_plan["domains"])
		),
		"seed_domains_by_zoom": {
			str(zoom): int(count)
			for zoom, count in sorted(
				zoom_counts.items()
			)
		},
		"halo_coarse_cells": int(
			halo_coarse_cells
		),
		"coarse_sea_raster": {
			"origin_x": raster["origin_x"],
			"origin_y": raster["origin_y"],
			"width": raster["width"],
			"height": raster["height"],
			"sea_cells": raster["sea_cells"],
			"geometry_count": (
				raster["geometry_count"]
			),
			"bounds": raster["bounds"],
		},
		"initial_domain_ids": ids,
	}


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Plant konservativ die initialen Sea-Seed-Domains "
			"eines adaptiven Work-Region-Plans."
		)
	)
	parser.add_argument("--adaptive-plan", required=True)
	parser.add_argument("--parent-grid", required=True)
	parser.add_argument("--sea-vector", required=True)
	parser.add_argument("--coarse-factor", type=int, required=True)
	parser.add_argument(
		"--halo-coarse-cells",
		type=int,
		default=1,
	)
	parser.add_argument("--output", required=True)
	args = parser.parse_args()

	plan = json.loads(
		Path(args.adaptive_plan).read_text(
			encoding="utf-8"
		)
	)
	parent_grid = json.loads(
		Path(args.parent_grid).read_text(
			encoding="utf-8"
		)
	)["grid"]

	report = plan_seed_domains(
		plan,
		parent_grid,
		args.sea_vector,
		coarse_factor=args.coarse_factor,
		halo_coarse_cells=args.halo_coarse_cells,
	)

	Path(args.output).write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)
	print(json.dumps({
		key: report[key]
		for key in (
			"domain_count",
			"seed_domain_count",
			"seed_domain_fraction",
			"seed_domains_by_zoom",
			"coarse_sea_raster",
		)
	}, indent=2))


if __name__ == "__main__":
	main()
