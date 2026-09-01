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


def main():
	# Mehrere 3x3-Domains. Der direkte Weg nach rechts ist höher,
	# ein günstigerer Weg läuft unten herum und verbessert später
	# bereits erreichte Domains. Damit wird auch die erneute
	# Verarbeitung nach verbesserten Randwerten geprüft.
	elevation = np.asarray([
		[-5.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0],
		[-5.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0],
		[-5.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0],
		[-5.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0],
		[-5.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0],
		[-5.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0],
		[-5.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
		[-5.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
		[-5.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
	], dtype=np.float32)

	sea = np.zeros(elevation.shape, dtype=np.uint8)
	sea[:, 0] = 1

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
		land_path = tmp / "land.bit"
		split_path = tmp / "split.u8"
		report_path = tmp / "report.json"

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

		land = (
			(global_threshold != sentinel)
			& (sea == 0)
		)
		pack_mask(land, land_path)

		subprocess.run([
			"python",
			str(
				ROOT
				/ "scripts"
				/ "process_component_domains.py"
			),
			"--elevation", str(elevation_path),
			"--sea-mask", str(sea_path),
			"--land-mask", str(land_path),
			"--output", str(split_path),
			"--work-dir", str(tmp / "domains"),
			"--solver",
			str(ROOT / "build" / "priority_flood_quantized"),
			"--levels", levels,
			"--width", str(elevation.shape[1]),
			"--height", str(elevation.shape[0]),
			"--domain-width", "3",
			"--domain-height", "3",
			"--report", str(report_path),
		], check=True)

		split = np.fromfile(
			split_path,
			dtype=np.uint8,
		).reshape(elevation.shape)

		if not np.array_equal(
			split[land],
			global_threshold[land],
		):
			raise AssertionError(
				"Domain-Splitting unterscheidet sich vom "
				"globalen Priority Flood."
			)

		if not np.all(split[~land] == sentinel):
			raise AssertionError(
				"Außerhalb der Component muss Sentinel stehen."
			)

		report = json.loads(report_path.read_text())
		if report["domain_count"] < 3:
			raise AssertionError(
				"Test hat zu wenige Domains erzeugt."
			)
		if report["solver_runs"] <= report["domain_count"]:
			raise AssertionError(
				"Test hat keine erneute Domain-Verarbeitung "
				"nach Randverbesserung ausgelöst."
			)
		if report["max_domain_runs"] < 2:
			raise AssertionError(
				"Keine Domain wurde mindestens zweimal gerechnet."
			)

	print("ok")


if __name__ == "__main__":
	main()
