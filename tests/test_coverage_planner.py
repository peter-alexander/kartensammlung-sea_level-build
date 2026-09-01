#!/usr/bin/env python3

import math
import sys
from pathlib import Path

import mapbox_vector_tile
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from coverage_planner import (
	context_bounds_for_bbox,
	decode_coverage_tile,
	ground_resolution,
	minimum_zoom_for_ground_resolution,
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
	if recommended_zoom(52.0, 6.0) != 13:
		raise AssertionError("52°N / 6m muss ungefähr Z13 ergeben.")
	if recommended_zoom(52.0, 3.0) != 14:
		raise AssertionError("52°N / 3m muss ungefähr Z14 ergeben.")

	if minimum_zoom_for_ground_resolution(52.0, 5.0) != 14:
		raise AssertionError(
			"5m-Source darf bei 52°N nicht gröber als Z14 verarbeitet werden."
		)
	if minimum_zoom_for_ground_resolution(52.0, 10.0) != 13:
		raise AssertionError(
			"10m-Source benötigt bei 52°N mindestens Z13."
		)
	if minimum_zoom_for_ground_resolution(52.0, 1.0) != 16:
		raise AssertionError(
			"1m-Source benötigt bei 52°N mindestens Z16."
		)

	tier_5m = source_tier(5.0)
	if tier_5m["automatic_tier"] != 2:
		raise AssertionError("5m-Quelle muss Tier 2 sein.")

	five_meter = processing_recommendations(
		52.0,
		tier_5m,
		5.0,
	)
	if five_meter["recommended_target_ground_resolution_m"] != 6.0:
		raise AssertionError(five_meter)
	if five_meter["recommended_processing_zoom"] != 13:
		raise AssertionError(
			"5m-Quelle bleibt vorerst bei der ausführbaren Z13-Empfehlung."
		)
	if five_meter["source_fidelity_processing_zoom"] != 14:
		raise AssertionError(five_meter)
	if not five_meter["source_fidelity_undersampled_by_recommendation"]:
		raise AssertionError(five_meter)

	tier_10m = source_tier(10.0)
	ten_meter = processing_recommendations(
		52.0,
		tier_10m,
		10.0,
	)
	if ten_meter["recommended_target_ground_resolution_m"] != 10.0:
		raise AssertionError(ten_meter)
	if ten_meter["recommended_processing_zoom"] != 12:
		raise AssertionError(
			"10m-Quelle bleibt vorerst bei der ausführbaren Z12-Empfehlung."
		)
	if ten_meter["source_fidelity_processing_zoom"] != 13:
		raise AssertionError(ten_meter)
	if not ten_meter["source_fidelity_undersampled_by_recommendation"]:
		raise AssertionError(ten_meter)

	tier_1m = source_tier(1.0)
	if tier_1m["automatic_tier"] != 2:
		raise AssertionError("1m-Quelle bleibt automatisch Tier 2.")
	if not tier_1m["tier3_candidate"]:
		raise AssertionError("1m-Quelle muss Tier-3-QA-Kandidat sein.")

	one_meter = processing_recommendations(
		52.0,
		tier_1m,
		1.0,
	)
	if one_meter["recommended_processing_zoom"] != 13:
		raise AssertionError(
			"1m-Quelle darf automatisch nicht feiner als ungefähr 6m werden."
		)
	if one_meter["tier3_candidate_processing_zoom"] != 14:
		raise AssertionError(
			"1m-Quelle soll ungefähr 3m nur als Tier-3-QA-Kandidat erhalten."
		)
	if one_meter["source_fidelity_processing_zoom"] != 16:
		raise AssertionError(one_meter)

	if source_tier(20.0)["automatic_tier"] != 1:
		raise AssertionError(
			"20m-Quelle soll keine automatische Verfeinerung auslösen."
		)

	assert_close(
		ground_resolution(52.0, 12),
		11.765,
		tolerance=0.05,
	)
	assert_close(
		ground_resolution(52.0, 13),
		5.883,
		tolerance=0.05,
	)


def test_tile_bbox_exclusive():
	zoom = 8
	west, south, east, north = tile_bounds_lonlat(130, 84, zoom)
	tiles = tiles_for_bbox((west, south, east, north), zoom)

	if tiles != [(130, 84)]:
		raise AssertionError(f"expected one tile, got {tiles}")


def test_context_bounds():
	zoom = 8
	west, south, east, north = tile_bounds_lonlat(130, 84, zoom)
	context = context_bounds_for_bbox(
		(west, south, east, north),
		zoom,
		1,
	)

	expected_west, _s, _e, expected_north = tile_bounds_lonlat(
		129,
		83,
		zoom,
	)
	_w, expected_south, expected_east, _n = tile_bounds_lonlat(
		131,
		85,
		zoom,
	)

	for actual, expected in zip(
		context,
		(
			expected_west,
			expected_south,
			expected_east,
			expected_north,
		),
	):
		assert_close(actual, expected, tolerance=1e-6)


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
	test_context_bounds()
	test_mvt_transform()
	print("ok")


if __name__ == "__main__":
	main()
