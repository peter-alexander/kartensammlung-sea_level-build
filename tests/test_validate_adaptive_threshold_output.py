#!/usr/bin/env python3

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from process_adaptive_lazy_domains import checkpoint_signature
from validate_adaptive_threshold_output import (
	validate_adaptive_threshold_output,
)


LEVELS = "0,1,2"
SENTINEL = 3


def plan_data():
	return {
		"component_id": 1,
		"parent_zoom": 0,
		"coarse_factor": 1,
		"domains": [
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
				"fine_cells": 1,
			},
			{
				"id": 2,
				"zoom": 0,
				"coarse_x0": 1,
				"coarse_y0": 0,
				"coarse_width": 1,
				"coarse_height": 1,
				"fine_pixels_per_coarse_cell": 1,
				"fine_width": 1,
				"fine_height": 1,
				"fine_cells": 1,
			},
		],
	}


def write_checkpoint(path, plan, *, broken_boundary=False):
	domains = plan["domains"]
	signature = checkpoint_signature(domains, LEVELS)

	# Reihenfolge pro Domain: top, bottom, left, right.
	incoming = np.asarray([
		SENTINEL,
		SENTINEL,
		SENTINEL,
		1,
		SENTINEL,
		SENTINEL,
		SENTINEL if broken_boundary else 1,
		SENTINEL,
	], dtype=np.uint8)
	metadata = {
		"schema_version": 1,
		"signature": signature,
		"completed": True,
		"counters": {
			"solver_runs": 2,
		},
	}
	with Path(path).open("wb") as target:
		np.savez_compressed(
			target,
			metadata=np.asarray(
				json.dumps(metadata),
				dtype=np.str_,
			),
			incoming=incoming,
			runs=np.asarray([1, 1], dtype=np.int64),
			land_cells=np.asarray([1, 1], dtype=np.int64),
			queue=np.asarray([], dtype=np.int64),
		)


def write_fixture(tmp, *, broken_boundary=False):
	plan = plan_data()
	plan_path = tmp / "plan.json"
	plan_path.write_text(
		json.dumps(plan, indent=2) + "\n",
		encoding="utf-8",
	)

	threshold_dir = tmp / "thresholds"
	threshold_dir.mkdir()
	np.asarray([1], dtype=np.uint8).tofile(
		threshold_dir / "r1-c0.u8"
	)
	np.asarray([1], dtype=np.uint8).tofile(
		threshold_dir / "r2-c0.u8"
	)

	checkpoint = tmp / "checkpoint.npz"
	write_checkpoint(
		checkpoint,
		plan,
		broken_boundary=broken_boundary,
	)

	components = {
		"width": 2,
		"height": 1,
		"span_record_bytes": 12,
		"components": [
			{
				"id": 1,
				"cells": 2,
				"span_offset_records": 0,
				"span_count": 1,
			},
		],
	}
	components_path = tmp / "components.json"
	components_path.write_text(
		json.dumps(components, indent=2) + "\n",
		encoding="utf-8",
	)
	np.asarray(
		[[0, 0, 1]],
		dtype="<u4",
	).tofile(tmp / "components.rle")

	parent_grid = {
		"grid": {
			"zoom": 0,
			"tile_size": 512,
			"x_min": 0,
			"y_min": 0,
		},
	}
	parent_grid_path = tmp / "grid.json"
	parent_grid_path.write_text(
		json.dumps(parent_grid, indent=2) + "\n",
		encoding="utf-8",
	)

	return {
		"plan": plan,
		"threshold_dir": threshold_dir,
		"checkpoint": checkpoint,
		"components": components_path,
		"spans": tmp / "components.rle",
		"parent_grid": parent_grid_path,
	}


def main():
	with tempfile.TemporaryDirectory() as directory:
		tmp = Path(directory)
		fixture = write_fixture(tmp)
		manifest_path = tmp / "manifest.json"
		report = validate_adaptive_threshold_output(
			plan=fixture["plan"],
			threshold_dir=fixture["threshold_dir"],
			checkpoint_path=fixture["checkpoint"],
			levels_csv=LEVELS,
			components_report_path=fixture["components"],
			spans_path=fixture["spans"],
			parent_grid_path=fixture["parent_grid"],
			manifest_output=manifest_path,
		)

		if report["fixed_point"]["adjacency_count"] != 1:
			raise AssertionError(report)
		if report["fixed_point"]["directed_edge_checks"] != 2:
			raise AssertionError(report)
		if report["fixed_point"]["improvable_pixels"] != 0:
			raise AssertionError(report)
		if report["component_partition"]["missing_cells"] != 0:
			raise AssertionError(report)
		if report["component_partition"]["overlap_cells"] != 0:
			raise AssertionError(report)
		if not report["reconstruction"]["spatial_mapping_valid"]:
			raise AssertionError(report)

		manifest = json.loads(
			manifest_path.read_text(encoding="utf-8")
		)
		if manifest["domain_count"] != 2:
			raise AssertionError(manifest)
		if manifest["domains"][0]["global_pixel_x0"] != 0:
			raise AssertionError(manifest)
		if manifest["domains"][1]["global_pixel_x0"] != 1:
			raise AssertionError(manifest)

	with tempfile.TemporaryDirectory() as directory:
		tmp = Path(directory)
		fixture = write_fixture(
			tmp,
			broken_boundary=True,
		)
		failed = False
		try:
			validate_adaptive_threshold_output(
				plan=fixture["plan"],
				threshold_dir=fixture["threshold_dir"],
				checkpoint_path=fixture["checkpoint"],
				levels_csv=LEVELS,
			)
		except AssertionError as error:
			if "Boundary-Fixpunkt" not in str(error):
				raise
			failed = True
		if not failed:
			raise AssertionError(
				"Validator muss einen noch verbesserbaren Rand ablehnen."
			)

	print("ok")


if __name__ == "__main__":
	main()
