#!/usr/bin/env python3

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plan_lazy_work_region_domains import (
	plan_domains_from_grids,
)


def main():
	parent_grid = {
		"width": 8,
		"height": 8,
		"left": 0.0,
		"top": 80.0,
		"resolution": 10.0,
	}
	fine_grid = {
		"width": 16,
		"height": 16,
		"left": 0.0,
		"top": 80.0,
		"resolution": 5.0,
	}
	component = {
		"id": 7,
		"rank": 1,
		"cells": 3,
		"span_count": 2,
	}
	spans = [
		(1, 1, 2),
		(2, 1, 1),
	]

	report = plan_domains_from_grids(
		component,
		spans,
		parent_grid,
		fine_grid,
		coarse_factor=2,
		domain_width=4,
		domain_height=4,
	)

	if report["fine_pixels_per_coarse_cell"] != 4:
		raise AssertionError(report)
	if report["full_bbox_domain_count"] != 16:
		raise AssertionError(report)

	keys = {
		(
			domain["grid_row"],
			domain["grid_col"],
		)
		for domain in report["domains"]
	}
	expected = {
		(1, 1),
		(1, 2),
		(2, 1),
		(2, 2),
	}
	if keys != expected:
		raise AssertionError(
			f"expected={expected} actual={keys}"
		)
	if report["active_domain_count"] != 4:
		raise AssertionError(report)
	if abs(report["active_domain_fraction"] - 0.25) > 1e-12:
		raise AssertionError(report)

	print("ok")


if __name__ == "__main__":
	main()
