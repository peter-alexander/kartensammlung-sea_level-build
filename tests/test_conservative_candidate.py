#!/usr/bin/env python3

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def run_candidate(elevation, sea, output, report):
	subprocess.run([
		str(ROOT / "build" / "candidate_mask_70"),
		"--elevation", str(elevation),
		"--sea-mask", str(sea),
		"--output", str(output),
		"--report", str(report),
		"--width", "8" if "fine" in output.name else "4",
		"--height", "8" if "fine" in output.name else "4",
		"--max-level", "70",
	], check=True)


def main():
	elevation = np.full((8, 8), 100.0, dtype=np.float32)
	elevation[0, 0:4] = 10.0
	elevation[:, 3] = 10.0
	elevation[7, 7] = 10.0

	sea = np.zeros((8, 8), dtype=np.uint8)
	sea[0, 0] = 1

	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		fine_elevation = tmp / "fine-elevation.f32"
		fine_sea = tmp / "fine-sea.u8"
		fine_mask = tmp / "fine-candidate.bit"
		fine_report = tmp / "fine-report.json"
		coarse_elevation = tmp / "coarse-elevation.f32"
		coarse_sea = tmp / "coarse-sea.u8"
		coarse_pure_sea = tmp / "coarse-pure-sea.u8"
		coarse_report = tmp / "coarse-input-report.json"
		coarse_mask = tmp / "coarse-candidate.bit"
		coarse_candidate_report = tmp / "coarse-candidate-report.json"
		comparison_path = tmp / "comparison.json"

		elevation.tofile(fine_elevation)
		sea.tofile(fine_sea)

		run_candidate(
			fine_elevation,
			fine_sea,
			fine_mask,
			fine_report,
		)

		subprocess.run([
			"python",
			str(ROOT / "scripts" / "build_conservative_candidate_coarse.py"),
			"--elevation", str(fine_elevation),
			"--sea-mask", str(fine_sea),
			"--output-elevation", str(coarse_elevation),
			"--output-sea-mask", str(coarse_sea),
			"--output-pure-sea-mask", str(coarse_pure_sea),
			"--report", str(coarse_report),
			"--width", "8",
			"--height", "8",
			"--factor", "2",
			"--chunk-coarse-rows", "1",
		], check=True)

		run_candidate(
			coarse_elevation,
			coarse_sea,
			coarse_mask,
			coarse_candidate_report,
		)

		subprocess.run([
			"python",
			str(ROOT / "scripts" / "compare_candidate_masks.py"),
			"--fine-mask", str(fine_mask),
			"--coarse-mask", str(coarse_mask),
			"--sea-mask", str(fine_sea),
			"--output", str(comparison_path),
			"--width", "8",
			"--height", "8",
			"--factor", "2",
			"--chunk-coarse-rows", "1",
		], check=True)

		coarse_input = json.loads(coarse_report.read_text())
		comparison = json.loads(comparison_path.read_text())

		if coarse_input["coarse_width"] != 4:
			raise AssertionError(coarse_input)
		if coarse_input["coarse_height"] != 4:
			raise AssertionError(coarse_input)
		if coarse_input["elevation_rule"] != "minimum-of-finite-children":
			raise AssertionError(coarse_input)
		if coarse_input["sea_rule"] != "logical-or-of-children":
			raise AssertionError(coarse_input)
		if (
			coarse_input["pure_sea_rule"]
			!= "logical-and-of-children"
		):
			raise AssertionError(coarse_input)
		if coarse_input["pure_sea_coarse_cells"] != 0:
			raise AssertionError(coarse_input)

		pure_sea = np.fromfile(
			coarse_pure_sea,
			dtype=np.uint8,
		).reshape((4, 4))
		if np.count_nonzero(pure_sea) != 0:
			raise AssertionError(pure_sea)

		if comparison["false_negative_cells"] != 0:
			raise AssertionError(comparison)
		if comparison["false_negative_land_cells"] != 0:
			raise AssertionError(comparison)
		if comparison["false_positive_cells"] <= 0:
			raise AssertionError(
				"Konservatives Hochskalieren soll im Test zusätzliche "
				"False Positives erzeugen."
			)
		if (
			comparison["conservative_candidate_cells"]
			< comparison["fine_candidate_cells"]
		):
			raise AssertionError(comparison)

	print("ok")


if __name__ == "__main__":
	main()
