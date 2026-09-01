#!/usr/bin/env python3

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_phase1a_dem import overzoom_parent_tile


def main():
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

	try:
		overzoom_parent_tile(
			parent,
			target_x=0,
			target_y=0,
			target_zoom=1,
			parent_zoom=1,
		)
	except ValueError:
		pass
	else:
		raise AssertionError(
			"parent_zoom >= target_zoom muss abgelehnt werden."
		)

	print("ok")


if __name__ == "__main__":
	main()
