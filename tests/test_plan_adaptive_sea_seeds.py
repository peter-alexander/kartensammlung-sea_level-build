#!/usr/bin/env python3

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plan_adaptive_sea_seeds import select_seed_domains


def main():
	sea = np.zeros((6, 8), dtype=np.uint8)
	sea[1, 1] = 1
	sea[4, 6] = 1

	domains = [
		{
			"id": 1,
			"coarse_x0": 1,
			"coarse_y0": 1,
			"coarse_width": 2,
			"coarse_height": 2,
		},
		{
			"id": 2,
			"coarse_x0": 4,
			"coarse_y0": 1,
			"coarse_width": 1,
			"coarse_height": 2,
		},
		{
			"id": 3,
			"coarse_x0": 5,
			"coarse_y0": 3,
			"coarse_width": 1,
			"coarse_height": 1,
		},
	]

	direct = select_seed_domains(
		domains,
		sea,
		mask_origin_x=0,
		mask_origin_y=0,
		halo_coarse_cells=0,
	)
	if direct != [1]:
		raise AssertionError(direct)

	with_halo = select_seed_domains(
		domains,
		sea,
		mask_origin_x=0,
		mask_origin_y=0,
		halo_coarse_cells=1,
	)
	if with_halo != [1, 3]:
		raise AssertionError(with_halo)

	print("ok")


if __name__ == "__main__":
	main()
