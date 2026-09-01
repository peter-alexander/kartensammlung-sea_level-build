#!/usr/bin/env python3

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plan_adaptive_work_region_domains import (
	pack_zoom_rectangles,
)


def main():
	assignment = np.asarray([
		[16, 16, 13, 13, 13],
		[16, 16, 13, 13, 13],
		[11, 11, 13, 13, 0],
		[11, 11, 11, 11, 0],
	], dtype=np.int16)

	z16 = pack_zoom_rectangles(
		assignment,
		16,
		origin_col=100,
		origin_row=200,
		scale=512,
		domain_pixels=512,
	)
	if len(z16) != 4:
		raise AssertionError(z16)
	if any(
		domain["coarse_cells"] != 1
		for domain in z16
	):
		raise AssertionError(z16)

	z13 = pack_zoom_rectangles(
		assignment,
		13,
		origin_col=100,
		origin_row=200,
		scale=64,
		domain_pixels=512,
	)
	if len(z13) != 2:
		raise AssertionError(z13)
	if sum(
		domain["coarse_cells"]
		for domain in z13
	) != 8:
		raise AssertionError(z13)
	if any(
		max(domain["fine_width"], domain["fine_height"])
		> 512
		for domain in z13
	):
		raise AssertionError(z13)

	z11 = pack_zoom_rectangles(
		assignment,
		11,
		origin_col=100,
		origin_row=200,
		scale=16,
		domain_pixels=512,
	)
	if len(z11) != 2:
		raise AssertionError(z11)
	if sum(
		domain["coarse_cells"]
		for domain in z11
	) != 6:
		raise AssertionError(z11)

	all_cells = (
		sum(domain["coarse_cells"] for domain in z16)
		+ sum(domain["coarse_cells"] for domain in z13)
		+ sum(domain["coarse_cells"] for domain in z11)
	)
	if all_cells != int(np.count_nonzero(assignment)):
		raise AssertionError(all_cells)

	print("ok")


if __name__ == "__main__":
	main()
