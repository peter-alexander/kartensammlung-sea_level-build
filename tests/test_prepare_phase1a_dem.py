#!/usr/bin/env python3

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_phase1a_dem import (
	overzoom_parent_tile,
	resolve_pmtiles_fallbacks,
)


class FakeReader:
	def __init__(self, available):
		self.available = set(available)

	def get(self, zoom, x, y):
		if (zoom, x, y) in self.available:
			return b"tile"
		return None


def test_overzoom():
	parent = np.arange(
		16,
		dtype=np.float32,
	).reshape((4, 4))

	child = overzoom_parent_tile(
		parent,
		target_x=1,
		target_y=1,
		target_zoom=1,
		parent_zoom=0,
	)
	expected = np.repeat(
		np.repeat(
			parent[2:4, 2:4],
			2,
			axis=0,
		),
		2,
		axis=1,
	)
	if not np.array_equal(child, expected):
		raise AssertionError(
			f"expected={expected.tolist()} actual={child.tolist()}"
		)

	parent_8 = np.arange(
		64,
		dtype=np.float32,
	).reshape((8, 8))
	child_factor_4 = overzoom_parent_tile(
		parent_8,
		target_x=6,
		target_y=5,
		target_zoom=4,
		parent_zoom=2,
	)
	expected_factor_4 = np.repeat(
		np.repeat(
			parent_8[2:4, 4:6],
			4,
			axis=0,
		),
		4,
		axis=1,
	)
	if not np.array_equal(
		child_factor_4,
		expected_factor_4,
	):
		raise AssertionError(
			"Faktor-4-Overzoom liefert den falschen Parent-Ausschnitt."
		)


def test_pmtiles_fallback_resolution():
	reader = FakeReader({
		(12, 5, 6),
		(11, 3, 3),
	})
	resolved, unresolved = resolve_pmtiles_fallbacks(
		[
			(10, 12),
			(11, 12),
			(12, 13),
			(30, 30),
		],
		target_zoom=13,
		fallback_min_zoom=11,
		reader=reader,
	)

	if resolved[(10, 12)]["parent_zoom"] != 12:
		raise AssertionError("Z12-Fallback wurde nicht bevorzugt.")
	if resolved[(11, 12)]["parent_zoom"] != 12:
		raise AssertionError("Gemeinsamer Z12-Parent fehlt.")
	if resolved[(12, 13)]["parent_zoom"] != 11:
		raise AssertionError("Z11-Fallback wurde nicht gefunden.")
	if unresolved != [(30, 30)]:
		raise AssertionError(
			f"Unerwartete unresolved-Liste: {unresolved}"
		)


def main():
	test_overzoom()
	test_pmtiles_fallback_resolution()
	print("ok")


if __name__ == "__main__":
	main()
