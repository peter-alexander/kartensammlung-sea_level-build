#!/usr/bin/env python3

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from process_lazy_domains import (
	process_lazy_domains,
	regular_domains,
)


LEVELS = (
	"0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,"
	"1,1.1,1.2,1.3,1.4,1.5,1.6,1.7,1.8,1.9,2,"
	"2.25,2.5,2.75,3,3.25,3.5,3.75,4,4.25,4.5,"
	"4.75,5,6,7,8,9,10,11,12,13,14,15,16,17,18,"
	"19,20,25,30,35,40,45,50,55,60,65,70"
)


def outside_sea(sea, domain):
	x0 = int(domain["x0"])
	y0 = int(domain["y0"])
	width = int(domain["width"])
	height = int(domain["height"])
	result = {
		"top": np.zeros(width, dtype=bool),
		"bottom": np.zeros(width, dtype=bool),
		"left": np.zeros(height, dtype=bool),
		"right": np.zeros(height, dtype=bool),
	}

	if y0 > 0:
		result["top"] = sea[
			y0 - 1,
			x0:x0 + width,
		] != 0
	if y0 + height < sea.shape[0]:
		result["bottom"] = sea[
			y0 + height,
			x0:x0 + width,
		] != 0
	if x0 > 0:
		result["left"] = sea[
			y0:y0 + height,
			x0 - 1,
		] != 0
	if x0 + width < sea.shape[1]:
		result["right"] = sea[
			y0:y0 + height,
			x0 + width,
		] != 0

	return result


def main():
	width = 12
	height = 8
	land = np.zeros((height, width), dtype=bool)

	# Langer, domainübergreifender Pfad.
	land[2, 1:11] = True
	land[2:7, 10] = True
	land[6, 2:11] = True
	land[4:7, 2] = True

	# Separater Küstenkontakt exakt über einer Domain-Grenze:
	# Sea x=3, Land x=4. Dafür ist external_sea erforderlich.
	land[0, 4:7] = True

	sea = np.zeros((height, width), dtype=np.uint8)
	sea[2, 0] = 1
	sea[0, 3] = 1

	elevation = np.full(
		(height, width),
		np.nan,
		dtype=np.float32,
	)
	values = (
		(
			np.arange(height, dtype=np.float32)[:, None] * 1.7
			+ np.arange(width, dtype=np.float32)[None, :] * 0.9
		)
		% 18.0
	)
	elevation[land] = values[land]

	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		elevation_path = tmp / "reference-elevation.f32"
		sea_path = tmp / "reference-sea.u8"
		reference_path = tmp / "reference.u8"
		lazy_path = tmp / "lazy.u8"
		work_dir = tmp / "lazy-work"

		elevation.tofile(elevation_path)
		sea.tofile(sea_path)

		subprocess.run([
			str(ROOT / "build" / "priority_flood_quantized"),
			"--elevation",
			str(elevation_path),
			"--sea-mask",
			str(sea_path),
			"--output",
			str(reference_path),
			"--width",
			str(width),
			"--height",
			str(height),
			"--levels",
			LEVELS,
			"--connectivity",
			"4",
		], check=True)

		def materialize(domain, domain_dir):
			x0 = int(domain["x0"])
			y0 = int(domain["y0"])
			local_width = int(domain["width"])
			local_height = int(domain["height"])
			x1 = x0 + local_width
			y1 = y0 + local_height

			local_elevation = np.array(
				elevation[y0:y1, x0:x1],
				copy=True,
			)
			local_sea = np.array(
				sea[y0:y1, x0:x1],
				copy=True,
			)
			local_land = np.array(
				land[y0:y1, x0:x1],
				copy=True,
			)

			elevation_target = (
				domain_dir / "elevation.f32"
			)
			sea_target = domain_dir / "sea.u8"
			land_target = domain_dir / "land.u8"

			local_elevation.tofile(elevation_target)
			local_sea.tofile(sea_target)
			local_land.astype(np.uint8).tofile(
				land_target
			)

			return {
				"elevation_path": str(elevation_target),
				"sea_mask_path": str(sea_target),
				"land_mask_path": str(land_target),
				"external_sea": outside_sea(
					sea,
					domain,
				),
			}

		report = process_lazy_domains(
			regular_domains(
				width,
				height,
				domain_width=4,
				domain_height=4,
			),
			materialize,
			lazy_path,
			work_dir,
			ROOT / "build" / "priority_flood_quantized",
			LEVELS,
			global_width=width,
			global_height=height,
		)

		reference = np.fromfile(
			reference_path,
			dtype=np.uint8,
		).reshape((height, width))
		lazy = np.fromfile(
			lazy_path,
			dtype=np.uint8,
		).reshape((height, width))
		sentinel = len(LEVELS.split(","))

		if not np.array_equal(
			reference[land],
			lazy[land],
		):
			differing = np.argwhere(
				land & (reference != lazy)
			)
			raise AssertionError(
				f"Lazy-Domain-Ergebnis weicht ab: {differing.tolist()}"
			)

		if np.any(lazy[~land] != sentinel):
			raise AssertionError(
				"Lazy-Ausgabe schreibt außerhalb der Work-Region."
			)

		if report["domain_count"] != 6:
			raise AssertionError(report)
		if report["materializations"] != report["solver_runs"]:
			raise AssertionError(report)
		if report["solver_runs"] <= report["domain_count"]:
			raise AssertionError(
				"Test muss mindestens eine Domain erneut rechnen."
			)
		if report["boundary_improvements"] <= 0:
			raise AssertionError(report)
		if report["external_sea_improvements"] <= 0:
			raise AssertionError(report)
		if report["peak_materialized_cells"] != 16:
			raise AssertionError(report)
		if not report["all_domain_work_deleted"]:
			raise AssertionError(report)

	print("ok")


if __name__ == "__main__":
	main()
