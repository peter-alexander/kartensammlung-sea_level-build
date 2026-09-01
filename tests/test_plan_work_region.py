#!/usr/bin/env python3

import sys
from pathlib import Path

from shapely.geometry import box, mapping
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plan_work_region import build_work_region_plan


def feature(source, geometry, resolution_m, zoom):
	return {
		"type": "Feature",
		"properties": {
			"source": source,
			"name": source,
			"resolution_m": resolution_m,
			"source_fidelity_processing_zoom": zoom,
			"source_fidelity_ground_resolution_m": resolution_m,
		},
		"geometry": mapping(geometry),
	}


def test_exact_coverage_geometry():
	work = box(0, 0, 10, 10)
	high = unary_union([
		box(0, 0, 1, 1),
		box(9, 9, 10, 10),
	])
	low = box(0, 0, 10, 10)

	plan = build_work_region_plan(
		work,
		[
			feature("low", low, 10.0, 13),
			feature("high", high, 1.0, 16),
		],
		base_zoom=11,
		tile_size=512,
		max_uniform_cells=1,
	)

	if plan["uniform_processing_zoom"] != 16:
		raise AssertionError(plan)

	effective = {
		item["source"]: item
		for item in plan["coverage"]["effective_sources"]
	}
	if set(effective) != {"high", "low"}:
		raise AssertionError(effective)

	high_fraction = effective["high"]["area_fraction"]
	low_fraction = effective["low"]["area_fraction"]

	if not (0.015 < high_fraction < 0.025):
		raise AssertionError(
			"Highres-Fläche muss aus der echten Geometrie und nicht "
			f"aus deren BBox stammen: {high_fraction}"
		)
	if not (0.97 < low_fraction < 0.99):
		raise AssertionError(low_fraction)

	total = (
		high_fraction
		+ low_fraction
		+ plan["coverage"]["uncovered_area_fraction"]
	)
	if abs(total - 1.0) > 1e-6:
		raise AssertionError(f"Flächenanteile summieren sich auf {total}.")

	if not plan["requires_work_region_split"]:
		raise AssertionError(
			"Ein absichtlich winziges Cell-Limit muss Split signalisieren."
		)


def main():
	test_exact_coverage_geometry()
	print("ok")


if __name__ == "__main__":
	main()
