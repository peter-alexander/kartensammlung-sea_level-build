#!/usr/bin/env python3

import math
import sys
from pathlib import Path

import mapbox_vector_tile
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from coverage_planner import (
	decode_coverage_tile,
	ground_resolution,
	processing_recommendations,
	recommended_zoom,
	source_tier,
	tile_bounds_lonlat,
	tiles_for_bbox,
)


def assert_close(actual, expected, tolerance=1e-6):
	if abs(actual - expected) > tolerance:
		raise AssertionError(
			f"expected={expected} actual={actual}"
		)


def test_resolution_rules():
	if recommended_zoom(52.0, 12.0) != 12:
		raise AssertionError("52°N / 12m muss ungefähr Z12 ergeben.")

	if source_tier(5.0)["automatic_tier"] != 2:
		raise AssertionError("5m-Quelle muss Tier 2 sein.")

	tier_1m = source_tier(1.0)
	if tier_1m["automatic_tier"] != 2:
		raise AssertionError("1m-Quelle bleibt automatisch Tier 2.")
	if not tier_1m["tier3_candidate"]:
		raise AssertionError("1m-Quelle muss Tier-3-QA-Kandidat sein.")

	if source_tier(20.0)["automatic_tier"] != 1:
		raise AssertionError("20m-Quelle soll keine automatische Verfeinerung auslösen.")

	one_meter = processing_recommendations(
		52.0,
		tier_1m,
		tier2_target_ground_resolution_m=12.0,
		tier3_target_ground_resolution_m=6.0,
	)
	if one_meter["recommended_processing_zoom"] != 12:
		raise AssertionError(
			"1m-Quelle muss automatisch Tier 2 / Z12 bleiben."
		)
	if one_meter["tier3_candidate_processing_zoom"] != 13:
		raise AssertionError(
			"1m-Quelle soll Z13 nur als Tier-3-QA-Kandidat erhalten."
		)

	assert_close(
		ground_resolution(52.0, 12),
		11.765,
		tolerance=0.05,
	)


def test_tile_bbox_exclusive():
	zoom = 8
	west, south, east, north = tile_bounds_lonlat(130, 84, zoom)
	tiles = tiles_for_bbox((west, south, east, north), zoom)

	if tiles != [(130, 84)]:
		raise AssertionError(f"expected one tile, got {tiles}")


def test_mvt_transform():
	zoom = 8
	x = 130
	y = 84
	geometry = box(0, 0, 4096, 4096)

	tile = mapbox_vector_tile.encode({
		"name": "coverage",
		"features": [{
			"geometry": geometry,
			"properties": {"source": "synthetic"},
		}],
	})

	features = decode_coverage_tile(tile, zoom, x, y)
	if len(features) != 1:
		raise AssertionError(features)

	source, decoded = features[0]
	if source != "synthetic":
		raise AssertionError(source)

	expected = tile_bounds_lonlat(x, y, zoom)
	actual = decoded.bounds

	for actual_value, expected_value in zip(actual, expected):
		assert_close(actual_value, expected_value, tolerance=1e-5)


def main():
	test_resolution_rules()
	test_tile_bbox_exclusive()
	test_mvt_transform()
	print("ok")


if __name__ == "__main__":
	main()
