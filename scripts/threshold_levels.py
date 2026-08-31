#!/usr/bin/env python3

import argparse
import bisect
import json
import math
from decimal import Decimal


SCHEME_NAME = "piecewise-v2"
THRESHOLD_BANDS = (
	{"min_m": 0.0, "max_m": 2.0, "step_m": 0.1},
	{"min_m": 2.0, "max_m": 5.0, "step_m": 0.25},
	{"min_m": 5.0, "max_m": 20.0, "step_m": 1.0},
	{"min_m": 20.0, "max_m": 70.0, "step_m": 5.0},
)


def _build_levels():
	levels = []

	for index, band in enumerate(THRESHOLD_BANDS):
		start = Decimal(str(band["min_m"]))
		end = Decimal(str(band["max_m"]))
		step = Decimal(str(band["step_m"]))
		value = start if index == 0 else start + step

		while value <= end:
			levels.append(float(value))
			value += step

	return tuple(levels)


LEVELS_M = _build_levels()
SENTINEL_CLASS = len(LEVELS_M)
SENTINEL_M = 71.0

if len(LEVELS_M) != 58:
	raise RuntimeError(f"Unerwartete Anzahl Threshold-Klassen: {len(LEVELS_M)}")
if LEVELS_M[0] != 0.0 or LEVELS_M[-1] != 70.0:
	raise RuntimeError("Threshold-Klassen müssen von 0 bis 70 m reichen.")


def format_level(value):
	value = float(value)
	if value.is_integer():
		return str(int(value))
	return f"{value:g}"


def levels_csv():
	return ",".join(format_level(value) for value in LEVELS_M)


def class_for_meters(value):
	value = float(value)

	if not math.isfinite(value):
		return SENTINEL_CLASS
	if value <= 0.0:
		return 0

	index = bisect.bisect_left(LEVELS_M, value - 1e-12)
	if index >= SENTINEL_CLASS:
		return SENTINEL_CLASS
	return index


def meters_for_class(value):
	index = int(value)
	if index == SENTINEL_CLASS:
		return SENTINEL_M
	if index < 0 or index >= SENTINEL_CLASS:
		raise ValueError(f"Ungültige Threshold-Klasse: {index}")
	return LEVELS_M[index]


def threshold_config(connectivity=4):
	return {
		"scheme": SCHEME_NAME,
		"min_m": LEVELS_M[0],
		"max_m": LEVELS_M[-1],
		"bands": [dict(band) for band in THRESHOLD_BANDS],
		"class_count": SENTINEL_CLASS,
		"connectivity": int(connectivity),
		"sentinel_class": SENTINEL_CLASS,
		"sentinel_m": SENTINEL_M,
		"rounding": "ceil-to-next-level",
	}


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--csv", action="store_true")
	parser.add_argument("--json", action="store_true")
	args = parser.parse_args()

	if args.csv:
		print(levels_csv())
		return

	data = threshold_config()
	data["levels_m"] = list(LEVELS_M)

	if args.json:
		print(json.dumps(data, indent=2))
	else:
		print(
			f"{SCHEME_NAME}: {len(LEVELS_M)} Klassen, "
			f"{LEVELS_M[0]:g}–{LEVELS_M[-1]:g} m; "
			f"Sentinel={SENTINEL_CLASS}"
		)


if __name__ == "__main__":
	main()
