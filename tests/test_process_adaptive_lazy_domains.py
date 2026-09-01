#!/usr/bin/env python3

import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from process_adaptive_lazy_domains import (
	build_adjacencies,
	process_adaptive_lazy_domains,
	resample_thresholds,
)


LEVELS = "0,1,2,3,4,5,6"


def main():
	domain_specs = [
		{
			"id": 1,
			"zoom": 0,
			"coarse_x0": 0,
			"coarse_y0": 0,
			"coarse_width": 1,
			"coarse_height": 1,
			"fine_pixels_per_coarse_cell": 1,
			"fine_width": 1,
			"fine_height": 1,
		},
		{
			"id": 2,
			"zoom": 1,
			"coarse_x0": 1,
			"coarse_y0": 0,
			"coarse_width": 1,
			"coarse_height": 1,
			"fine_pixels_per_coarse_cell": 2,
			"fine_width": 2,
			"fine_height": 2,
		},
		{
			"id": 3,
			"zoom": 0,
			"coarse_x0": 2,
			"coarse_y0": 0,
			"coarse_width": 1,
			"coarse_height": 1,
			"fine_pixels_per_coarse_cell": 1,
			"fine_width": 1,
			"fine_height": 1,
		},
	]

	data = {
		1: {
			"elevation": np.asarray(
				[[4.0]],
				dtype=np.float32,
			),
			"sea": np.asarray(
				[[0]],
				dtype=np.uint8,
			),
		},
		2: {
			"elevation": np.asarray(
				[
					[2.0, 3.0],
					[1.0, 5.0],
				],
				dtype=np.float32,
			),
			"sea": np.zeros(
				(2, 2),
				dtype=np.uint8,
			),
		},
		3: {
			"elevation": np.asarray(
				[[0.0]],
				dtype=np.float32,
			),
			"sea": np.asarray(
				[[1]],
				dtype=np.uint8,
			),
		},
	}

	# Die direkte Resampling-Regel selbst explizit absichern.
	fine = np.asarray([5, 3, 4, 6], dtype=np.uint8)
	reduced = resample_thresholds(
		fine,
		2,
		1,
		7,
	)
	if reduced.tolist() != [3, 4]:
		raise AssertionError(reduced)
	repeated = resample_thresholds(
		np.asarray([2, 5], dtype=np.uint8),
		1,
		2,
		7,
	)
	if repeated.tolist() != [2, 2, 5, 5]:
		raise AssertionError(repeated)

	domain_map = {
		item["id"]: {
			**item,
			"width": item["fine_width"],
			"height": item["fine_height"],
		}
		for item in domain_specs
	}
	adjacencies, _ = build_adjacencies(domain_map)
	if len(adjacencies) != 2:
		raise AssertionError(adjacencies)

	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		output_dir = tmp / "output"
		work_dir = tmp / "work"

		def materialize(domain, domain_dir):
			item = data[int(domain["id"])]
			elevation_path = (
				domain_dir / "elevation.f32"
			)
			sea_path = domain_dir / "sea.u8"
			land_path = domain_dir / "land.u8"

			item["elevation"].tofile(elevation_path)
			item["sea"].tofile(sea_path)
			np.ones(
				item["sea"].shape,
				dtype=np.uint8,
			).tofile(land_path)

			return {
				"elevation_path": str(elevation_path),
				"sea_mask_path": str(sea_path),
				"land_mask_path": str(land_path),
			}

		report = process_adaptive_lazy_domains(
			domain_specs,
			materialize,
			output_dir,
			work_dir,
			ROOT / "build" / "priority_flood_quantized",
			LEVELS,
		)

		left = np.fromfile(
			output_dir / "r1-c0.u8",
			dtype=np.uint8,
		).reshape((1, 1))
		middle = np.fromfile(
			output_dir / "r2-c1.u8",
			dtype=np.uint8,
		).reshape((2, 2))
		right = np.fromfile(
			output_dir / "r3-c0.u8",
			dtype=np.uint8,
		).reshape((1, 1))

		if right.tolist() != [[0]]:
			raise AssertionError(right)
		if middle.tolist() != [
			[3, 3],
			[3, 5],
		]:
			raise AssertionError(middle)
		if left.tolist() != [[4]]:
			raise AssertionError(left)

		if report["domain_count"] != 3:
			raise AssertionError(report)
		if report["adjacency_count"] != 2:
			raise AssertionError(report)
		if report["solver_runs"] <= 3:
			raise AssertionError(
				"Seedlose Domains müssen nach späteren "
				"Randverbesserungen erneut gerechnet werden."
			)
		if report["boundary_improvements"] <= 0:
			raise AssertionError(report)
		if report["peak_materialized_cells"] != 4:
			raise AssertionError(report)
		if not report["all_domain_work_deleted"]:
			raise AssertionError(report)

	print("ok")


if __name__ == "__main__":
	main()
