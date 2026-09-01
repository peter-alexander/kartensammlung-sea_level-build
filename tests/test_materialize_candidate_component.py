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


def unpack_mask(path, cells):
	return np.unpackbits(
		np.fromfile(path, dtype=np.uint8),
		bitorder="little",
	)[:cells].astype(bool)


def main():
	candidate = np.ones((5, 7), dtype=bool)
	sea = np.asarray([
		[0, 0, 1, 1, 1, 0, 0],
		[0, 0, 1, 1, 1, 0, 0],
		[0, 0, 1, 1, 1, 0, 0],
		[0, 0, 1, 1, 1, 0, 0],
		[0, 0, 1, 1, 1, 0, 0],
	], dtype=np.uint8)
	elevation = np.arange(
		35,
		dtype=np.float32,
	).reshape((5, 7))

	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		candidate_path = tmp / "candidate.bit"
		sea_path = tmp / "sea.u8"
		elevation_path = tmp / "elevation.f32"
		components_path = tmp / "components.json"
		spans_path = tmp / "components.rle"
		output_dir = tmp / "component"

		pack_mask(candidate, candidate_path)
		sea.tofile(sea_path)
		elevation.tofile(elevation_path)

		subprocess.run([
			str(ROOT / "build" / "candidate_land_components"),
			"--candidate-mask", str(candidate_path),
			"--sea-mask", str(sea_path),
			"--report", str(components_path),
			"--spans-output", str(spans_path),
			"--width", "7",
			"--height", "5",
		], check=True)

		components = json.loads(
			components_path.read_text()
		)
		component = components["components"][0]
		component_id = int(component["id"])

		subprocess.run([
			"python",
			str(
				ROOT
				/ "scripts"
				/ "materialize_candidate_component.py"
			),
			"--components-report", str(components_path),
			"--spans", str(spans_path),
			"--component-id", str(component_id),
			"--elevation", str(elevation_path),
			"--sea-mask", str(sea_path),
			"--output-dir", str(output_dir),
			"--global-width", "7",
			"--global-height", "5",
			"--halo", "1",
		], check=True)

		report = json.loads(
			(output_dir / "component.json").read_text()
		)
		window = report["window"]

		x0 = int(window["x0"])
		y0 = int(window["y0"])
		width = int(window["width"])
		height = int(window["height"])

		local_elevation = np.fromfile(
			output_dir / "elevation.f32",
			dtype=np.float32,
		).reshape((height, width))
		local_sea = np.fromfile(
			output_dir / "sea_mask.u8",
			dtype=np.uint8,
		).reshape((height, width))
		local_land = unpack_mask(
			output_dir / "land_mask.bit",
			width * height,
		).reshape((height, width))

		expected_elevation = elevation[
			y0:y0 + height,
			x0:x0 + width,
		]
		expected_sea = sea[
			y0:y0 + height,
			x0:x0 + width,
		]

		if not np.array_equal(
			local_elevation,
			expected_elevation,
		):
			raise AssertionError(report)
		if not np.array_equal(
			local_sea,
			expected_sea,
		):
			raise AssertionError(report)
		if int(np.count_nonzero(local_land)) != 10:
			raise AssertionError(report)

		# Der 1-Zellen-Halo muss die Meeresnachbarn
		# der Küstenkante enthalten.
		if not np.any(
			local_sea
			& np.roll(local_land, 1, axis=1)
		):
			raise AssertionError(
				"Lokales Fenster enthält keinen Sea-Halo."
			)

	print("ok")


if __name__ == "__main__":
	main()
