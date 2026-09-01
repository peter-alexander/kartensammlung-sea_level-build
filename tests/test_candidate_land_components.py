#!/usr/bin/env python3

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def pack_mask(mask, path):
	bits = np.packbits(
		mask.reshape(-1).astype(np.uint8),
		bitorder="little",
	)
	bits.tofile(path)


def main():
	# Zwei Landgebiete sind über dieselbe Meeresfläche verbunden.
	# Für die Komponentenzerlegung müssen es trotzdem zwei
	# unabhängige Land-Komponenten bleiben.
	candidate = np.asarray([
		[1, 1, 1, 1, 1, 1, 1],
		[1, 1, 1, 1, 1, 1, 1],
		[1, 1, 1, 1, 1, 1, 1],
		[1, 1, 1, 1, 1, 1, 1],
		[1, 1, 1, 1, 1, 1, 1],
	], dtype=bool)

	sea = np.asarray([
		[0, 0, 1, 1, 1, 0, 0],
		[0, 0, 1, 1, 1, 0, 0],
		[0, 0, 1, 1, 1, 0, 0],
		[0, 0, 1, 1, 1, 0, 0],
		[0, 0, 1, 1, 1, 0, 0],
	], dtype=np.uint8)

	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		candidate_path = tmp / "candidate.bit"
		sea_path = tmp / "sea.u8"
		report_path = tmp / "report.json"
		spans_path = tmp / "components.rle"

		pack_mask(candidate, candidate_path)
		sea.tofile(sea_path)

		subprocess.run([
			str(ROOT / "build" / "candidate_land_components"),
			"--candidate-mask", str(candidate_path),
			"--sea-mask", str(sea_path),
			"--report", str(report_path),
			"--spans-output", str(spans_path),
			"--width", str(candidate.shape[1]),
			"--height", str(candidate.shape[0]),
		], check=True)

		report = json.loads(report_path.read_text())

		if report["land_candidate_cells"] != 20:
			raise AssertionError(report)
		if report["sea_candidate_cells"] != 15:
			raise AssertionError(report)
		if report["component_count"] != 2:
			raise AssertionError(report)

		sizes = [
			component["cells"]
			for component in report["components"]
		]
		if sizes != [10, 10]:
			raise AssertionError(report)

		if any(
			component["coastal_cells"] != 5
			for component in report["components"]
		):
			raise AssertionError(report)

		if report["span_record_bytes"] != 12:
			raise AssertionError(report)
		if report["span_record_count"] != 10:
			raise AssertionError(report)
		if any(
			component["span_count"] != 5
			for component in report["components"]
		):
			raise AssertionError(report)

		spans = np.fromfile(
			spans_path,
			dtype="<u4",
		).reshape((-1, 3))
		if spans.shape != (10, 3):
			raise AssertionError(spans)

		expected_spans = {
			*( (row, 0, 1) for row in range(5) ),
			*( (row, 5, 6) for row in range(5) ),
		}
		actual_spans = {
			tuple(int(value) for value in span)
			for span in spans
		}
		if actual_spans != expected_spans:
			raise AssertionError(
				f"expected={expected_spans} actual={actual_spans}"
			)

	print("ok")


if __name__ == "__main__":
	main()
