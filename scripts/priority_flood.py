#!/usr/bin/env python3

import argparse
import heapq
import json
import math
from pathlib import Path


def _grid_shape(grid, name):
	if not isinstance(grid, list) or not grid:
		raise ValueError(f"{name} muss eine nicht-leere Liste von Zeilen sein.")

	width = None
	for row_index, row in enumerate(grid):
		if not isinstance(row, list) or not row:
			raise ValueError(f"{name}[{row_index}] muss eine nicht-leere Liste sein.")
		if width is None:
			width = len(row)
		elif len(row) != width:
			raise ValueError(f"{name} muss rechteckig sein.")

	return len(grid), width


def _validate_inputs(elevation, sea_mask):
	rows, cols = _grid_shape(elevation, "elevation")
	mask_rows, mask_cols = _grid_shape(sea_mask, "sea_mask")

	if (rows, cols) != (mask_rows, mask_cols):
		raise ValueError("elevation und sea_mask müssen dieselbe Rastergröße haben.")

	for row_index in range(rows):
		for col_index in range(cols):
			value = elevation[row_index][col_index]
			if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
				raise ValueError(
					f"elevation[{row_index}][{col_index}] muss eine endliche Zahl sein."
				)

			if not isinstance(sea_mask[row_index][col_index], bool):
				raise ValueError(
					f"sea_mask[{row_index}][{col_index}] muss true oder false sein."
				)

	return rows, cols


def _neighbor_offsets(connectivity):
	if connectivity == 4:
		return (
			(-1, 0),
			(0, -1),
			(0, 1),
			(1, 0),
		)

	if connectivity == 8:
		return (
			(-1, -1),
			(-1, 0),
			(-1, 1),
			(0, -1),
			(0, 1),
			(1, -1),
			(1, 0),
			(1, 1),
		)

	raise ValueError("connectivity muss 4 oder 8 sein.")


def compute_inundation_threshold(
	elevation,
	sea_mask,
	*,
	connectivity=8,
	sea_level_zero=0.0,
):
	"""
	Berechnet für jede Rasterzelle den niedrigsten Meeresspiegel, bei dem sie
	über einen zusammenhängenden Weg vom heutigen Meer erreichbar ist.

	Der Kostenwert eines Weges ist die höchste Geländehöhe entlang dieses Weges.
	Für jede Zelle wird der Weg mit dem niedrigsten solchen Maximalwert gesucht.

	Die heutigen Meereszellen starten bei sea_level_zero, standardmäßig 0 m.
	"""

	rows, cols = _validate_inputs(elevation, sea_mask)
	offsets = _neighbor_offsets(connectivity)

	threshold = [
		[math.inf for _ in range(cols)]
		for _ in range(rows)
	]
	queue = []

	for row in range(rows):
		for col in range(cols):
			if not sea_mask[row][col]:
				continue

			threshold[row][col] = float(sea_level_zero)
			heapq.heappush(queue, (float(sea_level_zero), row, col))

	if not queue:
		raise ValueError("sea_mask enthält keine Meereszelle.")

	while queue:
		current_threshold, row, col = heapq.heappop(queue)

		if current_threshold != threshold[row][col]:
			continue

		for row_offset, col_offset in offsets:
			next_row = row + row_offset
			next_col = col + col_offset

			if next_row < 0 or next_row >= rows or next_col < 0 or next_col >= cols:
				continue

			next_threshold = max(
				current_threshold,
				float(elevation[next_row][next_col]),
			)

			if next_threshold >= threshold[next_row][next_col]:
				continue

			threshold[next_row][next_col] = next_threshold
			heapq.heappush(
				queue,
				(next_threshold, next_row, next_col),
			)

	return threshold


def flood_mask_for_level(threshold, sea_level):
	rows, cols = _grid_shape(threshold, "threshold")
	level = float(sea_level)

	return [
		[
			float(threshold[row][col]) <= level
			for col in range(cols)
		]
		for row in range(rows)
	]


def _demo_input():
	# Spalte 0 ist heutiges Meer.
	# Eine geschlossene 8-m-Barriere trennt die -4-m-Senke vom Meer.
	return {
		"elevation": [
			[0, 2, 8, 4, 4, 4],
			[0, 2, 8, -4, -4, 4],
			[0, 2, 8, -4, -4, 12],
			[0, -2, 8, 4, 4, 4],
		],
		"sea_mask": [
			[True, False, False, False, False, False],
			[True, False, False, False, False, False],
			[True, False, False, False, False, False],
			[True, False, False, False, False, False],
		],
	}


def run_demo(connectivity=8):
	data = _demo_input()
	threshold = compute_inundation_threshold(
		data["elevation"],
		data["sea_mask"],
		connectivity=connectivity,
	)

	checks = {
		"Meer": threshold[0][0],
		"Küstenland_2m": threshold[0][1],
		"Küstenland_minus2m": threshold[3][1],
		"Barriere_8m": threshold[1][2],
		"Senke_minus4m": threshold[1][3],
		"Huegel_12m": threshold[2][5],
	}

	expected = {
		"Meer": 0.0,
		"Küstenland_2m": 2.0,
		"Küstenland_minus2m": 0.0,
		"Barriere_8m": 8.0,
		"Senke_minus4m": 8.0,
		"Huegel_12m": 12.0,
	}

	if checks != expected:
		raise AssertionError(
			f"Demo fehlgeschlagen. Erwartet {expected}, erhalten {checks}"
		)

	return {
		"connectivity": connectivity,
		"checks": checks,
		"threshold": threshold,
		"flood_at_5m": flood_mask_for_level(threshold, 5),
		"flood_at_8m": flood_mask_for_level(threshold, 8),
	}


def _load_json(path):
	with Path(path).open("r", encoding="utf-8") as handle:
		return json.load(handle)


def _write_json(path, value):
	serialized = json.dumps(
		value,
		ensure_ascii=False,
		indent=2,
		allow_nan=False,
	)

	if path:
		Path(path).write_text(serialized + "\n", encoding="utf-8")
	else:
		print(serialized)


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Berechnet aus DEM + heutiger Meer-Maske den niedrigsten "
			"Meeresspiegel, bei dem jede Rasterzelle vom Meer erreichbar ist."
		)
	)
	parser.add_argument(
		"--input",
		help="JSON mit elevation[][] und sea_mask[][].",
	)
	parser.add_argument(
		"--output",
		help="Ausgabe-JSON. Ohne Angabe wird nach stdout geschrieben.",
	)
	parser.add_argument(
		"--connectivity",
		type=int,
		choices=(4, 8),
		default=8,
		help="Nachbarschaft im Raster, Standard: 8.",
	)
	parser.add_argument(
		"--demo",
		action="store_true",
		help="Integrierten Test mit einer abgeschlossenen Senke ausführen.",
	)
	args = parser.parse_args()

	if args.demo:
		_write_json(args.output, run_demo(args.connectivity))
		return

	if not args.input:
		parser.error("--input oder --demo ist erforderlich.")

	data = _load_json(args.input)
	if not isinstance(data, dict):
		raise ValueError("Eingabe muss ein JSON-Objekt sein.")

	elevation = data.get("elevation")
	sea_mask = data.get("sea_mask")
	threshold = compute_inundation_threshold(
		elevation,
		sea_mask,
		connectivity=args.connectivity,
	)

	_write_json(
		args.output,
		{
			"connectivity": args.connectivity,
			"rows": len(threshold),
			"cols": len(threshold[0]),
			"threshold": threshold,
		},
	)


if __name__ == "__main__":
	main()
