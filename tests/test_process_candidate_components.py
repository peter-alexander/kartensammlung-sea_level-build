#!/usr/bin/env python3

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def pack_mask(mask, path):
	np.packbits(
		mask.reshape(-1).astype(np.uint8),
		bitorder="little",
	).tofile(path)


def assert_matches(
	path,
	candidate_land,
	global_threshold,
	sentinel,
):
	result = np.fromfile(
		path,
		dtype=np.uint8,
	).reshape(global_threshold.shape)

	if not np.array_equal(
		result[candidate_land],
		global_threshold[candidate_land],
	):
		raise AssertionError(
			"Serielle End-to-End-Pipeline unterscheidet "
			"sich vom globalen Priority Flood."
		)

	if not np.all(
		result[~candidate_land] == sentinel
	):
		raise AssertionError(
			"Außerhalb Candidate-Land muss Sentinel stehen."
		)


def main():
	elevation = np.asarray([
		[0.0, 0.2, -5.0, 0.1, 0.0],
		[0.0, 0.4, -5.0, 0.3, 0.0],
		[0.0, 0.6, -5.0, 0.5, 0.0],
		[0.0, 0.8, -5.0, 0.7, 0.0],
		[0.0, 1.0, -5.0, 0.9, 0.0],
	], dtype=np.float32)

	sea = np.zeros(elevation.shape, dtype=np.uint8)
	sea[:, 2] = 1

	levels = subprocess.check_output([
		"python",
		str(ROOT / "scripts" / "threshold_levels.py"),
		"--csv",
	], text=True).strip()
	sentinel = len(levels.split(","))

	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		elevation_path = tmp / "elevation.f32"
		sea_path = tmp / "sea.u8"
		global_path = tmp / "global.u8"
		candidate_path = tmp / "candidate.bit"
		components_path = tmp / "components.json"
		spans_path = tmp / "components.rle"
		serial_path = tmp / "serial.u8"
		split_path = tmp / "split.u8"

		elevation.tofile(elevation_path)
		sea.tofile(sea_path)

		subprocess.run([
			str(ROOT / "build" / "priority_flood_quantized"),
			"--elevation", str(elevation_path),
			"--sea-mask", str(sea_path),
			"--output", str(global_path),
			"--width", str(elevation.shape[1]),
			"--height", str(elevation.shape[0]),
			"--levels", levels,
			"--connectivity", "4",
		], check=True)

		global_threshold = np.fromfile(
			global_path,
			dtype=np.uint8,
		).reshape(elevation.shape)

		candidate_land = (
			(global_threshold != sentinel)
			& (sea == 0)
		)
		candidate = candidate_land | (sea != 0)
		pack_mask(candidate, candidate_path)

		subprocess.run([
			str(ROOT / "build" / "candidate_land_components"),
			"--candidate-mask", str(candidate_path),
			"--sea-mask", str(sea_path),
			"--report", str(components_path),
			"--spans-output", str(spans_path),
			"--width", str(elevation.shape[1]),
			"--height", str(elevation.shape[0]),
		], check=True)

		common = [
			"python",
			str(
				ROOT
				/ "scripts"
				/ "process_candidate_components.py"
			),
			"--components-report", str(components_path),
			"--spans", str(spans_path),
			"--elevation", str(elevation_path),
			"--sea-mask", str(sea_path),
			"--solver",
			str(ROOT / "build" / "priority_flood_land_mask"),
			"--levels", levels,
			"--global-width", str(elevation.shape[1]),
			"--global-height", str(elevation.shape[0]),
			"--halo", "1",
		]

		direct_result = subprocess.check_output([
			*common,
			"--output", str(serial_path),
			"--work-dir", str(tmp / "work-direct"),
		], text=True)
		direct_report = json.loads(direct_result)

		assert_matches(
			serial_path,
			candidate_land,
			global_threshold,
			sentinel,
		)

		if direct_report["split_components"] != 0:
			raise AssertionError(
				"Direkter Test darf keinen Domain-Fallback nutzen."
			)

		split_result = subprocess.check_output([
			*common,
			"--output", str(split_path),
			"--work-dir", str(tmp / "work-split"),
			"--max-direct-window-cells", "1",
			"--domain-solver",
			str(ROOT / "build" / "priority_flood_quantized"),
			"--domain-width", "2",
			"--domain-height", "2",
		], text=True)
		split_report = json.loads(split_result)

		assert_matches(
			split_path,
			candidate_land,
			global_threshold,
			sentinel,
		)

		if split_report["direct_components"] != 0:
			raise AssertionError(
				"Erzwungener Fallback hat eine Component direkt gerechnet."
			)
		if split_report["split_components"] != 2:
			raise AssertionError(
				"Erwartet wurden zwei gesplittete Components."
			)
		if split_report["split_solver_runs"] <= 0:
			raise AssertionError(
				"Domain-Fallback hat keinen Solver-Lauf gemeldet."
			)

		for work_name in ("work-direct", "work-split"):
			work_dir = tmp / work_name
			if (
				work_dir.exists()
				and any(work_dir.iterdir())
			):
				raise AssertionError(
					"Component-Arbeitsverzeichnisse wurden "
					"nicht freigegeben."
				)

	print("ok")


if __name__ == "__main__":
	main()
