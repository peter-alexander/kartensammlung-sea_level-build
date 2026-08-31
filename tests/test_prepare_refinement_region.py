#!/usr/bin/env python3

import json
import math
import sys
import tempfile
from pathlib import Path

from shapely.geometry import box, mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from coverage_planner import WEB_MERCATOR_WORLD, tile_bounds_lonlat
from prepare_refinement_region import prepare_region


def write_fixture(tmp):
	tmp.mkdir(parents=True, exist_ok=True)
	parent_grid = tmp / "parent-grid.json"
	sources = tmp / "sources.geojson"

	parent_zoom = 11
	parent_x_min = 1040
	parent_y_min = 670
	parent_x_max = 1041
	parent_y_max = 671

	west, _south, _east, north = tile_bounds_lonlat(
		parent_x_min,
		parent_y_min,
		parent_zoom,
	)
	_west, south, east, _north = tile_bounds_lonlat(
		parent_x_max,
		parent_y_max,
		parent_zoom,
	)

	parent_grid.write_text(
		json.dumps({
			"config": {
				"bounds": {
					"west": west,
					"south": south,
					"east": east,
					"north": north,
				},
			},
			"grid": {
				"zoom": parent_zoom,
				"tile_size": 512,
				"x_min": parent_x_min,
				"x_max": parent_x_max,
				"y_min": parent_y_min,
				"y_max": parent_y_max,
			},
		}),
		encoding="utf-8",
	)

	core_x = 2081
	core_y = 1341
	core_west, core_south, core_east, core_north = (
		tile_bounds_lonlat(
			core_x,
			core_y,
			12,
		)
	)

	sources.write_text(
		json.dumps({
			"type": "FeatureCollection",
			"features": [{
				"type": "Feature",
				"properties": {
					"source": "synthetic",
					"resolution_m": 5.0,
				},
				"geometry": mapping(
					box(
						core_west,
						core_south,
						core_east,
						core_north,
					)
				),
			}],
		}),
		encoding="utf-8",
	)

	return parent_grid, sources, (west, south, east, north)


def test_legacy_tile_halo(tmp):
	parent_grid, sources, parent_bounds = write_fixture(tmp)
	output_config = tmp / "legacy-fine.json"
	output_core = tmp / "legacy-core.geojson"

	report = prepare_region(
		sources,
		"synthetic",
		parent_grid,
		fine_zoom=12,
		halo_tiles=1,
		transition_buffer_pixels=0,
		output_config=output_config,
		output_core=output_core,
	)

	if report["core_tile_range"]["x"] != [2081, 2081]:
		raise AssertionError(report)
	if report["core_tile_range"]["y"] != [1341, 1341]:
		raise AssertionError(report)
	if report["work_tile_range"]["x"] != [2080, 2082]:
		raise AssertionError(report)
	if report["work_tile_range"]["y"] != [1340, 1342]:
		raise AssertionError(report)
	if report["work_tile_count"] != 9:
		raise AssertionError(report)

	core_feature = json.loads(output_core.read_text())
	if core_feature["properties"]["parent_target_bounds"] != list(
		parent_bounds
	):
		raise AssertionError(core_feature)

	fine_config = json.loads(output_config.read_text())
	if fine_config["threshold"]["max_m"] != 70.0:
		raise AssertionError(fine_config["threshold"])
	if fine_config["threshold"]["class_count"] != 58:
		raise AssertionError(fine_config["threshold"])


def test_physical_width_is_zoom_stable(tmp):
	parent_grid, sources, _parent_bounds = write_fixture(tmp)

	z12_resolution = WEB_MERCATOR_WORLD / ((2 ** 12) * 512)
	transition_projected_m = 128 * z12_resolution
	halo_projected_m = 512 * z12_resolution

	z12 = prepare_region(
		sources,
		"synthetic",
		parent_grid,
		fine_zoom=12,
		halo_projected_m=halo_projected_m,
		transition_buffer_projected_m=transition_projected_m,
		output_config=tmp / "z12.json",
		output_core=tmp / "z12-core.geojson",
	)
	z13 = prepare_region(
		sources,
		"synthetic",
		parent_grid,
		fine_zoom=13,
		halo_projected_m=halo_projected_m,
		transition_buffer_projected_m=transition_projected_m,
		output_config=tmp / "z13.json",
		output_core=tmp / "z13-core.geojson",
	)

	if z12["halo_tiles"] != 1:
		raise AssertionError(z12)
	if z13["halo_tiles"] != 2:
		raise AssertionError(z13)

	if not math.isclose(
		z12["transition_buffer_pixels"],
		128.0,
		rel_tol=0,
		abs_tol=1e-9,
	):
		raise AssertionError(z12)
	if not math.isclose(
		z13["transition_buffer_pixels"],
		256.0,
		rel_tol=0,
		abs_tol=1e-9,
	):
		raise AssertionError(z13)

	for report in (z12, z13):
		if not math.isclose(
			report["transition_buffer_projected_m"],
			transition_projected_m,
			rel_tol=0,
			abs_tol=1e-9,
		):
			raise AssertionError(report)
		if report["halo_projected_m"] + 1e-9 < halo_projected_m:
			raise AssertionError(report)


def main():
	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		test_legacy_tile_halo(tmp / "legacy")
		(tmp / "physical").mkdir()
		test_physical_width_is_zoom_stable(tmp / "physical")

	print("ok")


if __name__ == "__main__":
	main()
