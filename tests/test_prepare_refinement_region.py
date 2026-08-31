#!/usr/bin/env python3

import json
import sys
import tempfile
from pathlib import Path

from shapely.geometry import box, mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from coverage_planner import tile_bounds_lonlat
from prepare_refinement_region import prepare_region


def main():
	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		parent_grid = tmp / "parent-grid.json"
		sources = tmp / "sources.geojson"
		output_config = tmp / "fine.json"
		output_core = tmp / "core.geojson"

		parent_zoom = 11
		fine_zoom = 12
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
				fine_zoom,
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

		report = prepare_region(
			sources,
			"synthetic",
			parent_grid,
			fine_zoom=fine_zoom,
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
		properties = core_feature["properties"]
		if properties["parent_target_bounds"] != [
			west,
			south,
			east,
			north,
		]:
			raise AssertionError(properties)
		if any(properties["clipped_sides"].values()):
			raise AssertionError(properties)

		fine_config = json.loads(output_config.read_text())
		if fine_config["threshold"]["max_m"] != 70.0:
			raise AssertionError(fine_config["threshold"])
		if fine_config["threshold"]["class_count"] != 58:
			raise AssertionError(fine_config["threshold"])

	print("ok")


if __name__ == "__main__":
	main()
