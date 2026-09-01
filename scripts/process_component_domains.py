#!/usr/bin/env python3

import argparse
import json
import shutil
import subprocess
from collections import deque
from pathlib import Path

import numpy as np


def require_file_size(path, expected):
	path = Path(path)
	actual = path.stat().st_size
	if actual != expected:
		raise ValueError(
			f"Unerwartete Dateigröße für {path}: "
			f"erwartet={expected}, tatsächlich={actual}"
		)


def read_window(
	path,
	*,
	dtype,
	source_width,
	x0,
	y0,
	width,
	height,
):
	dtype = np.dtype(dtype)
	result = np.empty(
		(height, width),
		dtype=dtype,
	)

	with Path(path).open("rb") as source:
		for local_row in range(height):
			source_row = y0 + local_row
			offset = (
				(source_row * source_width + x0)
				* dtype.itemsize
			)
			source.seek(offset)
			raw = source.read(width * dtype.itemsize)
			if len(raw) != width * dtype.itemsize:
				raise RuntimeError(
					"Quellfenster konnte nicht vollständig "
					"gelesen werden."
				)
			result[local_row] = np.frombuffer(
				raw,
				dtype=dtype,
				count=width,
			)

	return result


def read_packed_window(
	path,
	*,
	source_width,
	x0,
	y0,
	width,
	height,
):
	result = np.zeros(
		(height, width),
		dtype=bool,
	)

	with Path(path).open("rb") as source:
		for local_row in range(height):
			bit_start = (
				(y0 + local_row) * source_width
				+ x0
			)
			byte_start = bit_start >> 3
			bit_offset = bit_start & 7
			byte_count = (
				bit_offset + width + 7
			) // 8

			source.seek(byte_start)
			raw = source.read(byte_count)
			if len(raw) != byte_count:
				raise RuntimeError(
					"Packed-Landmaske konnte nicht "
					"vollständig gelesen werden."
				)

			unpacked = np.unpackbits(
				np.frombuffer(raw, dtype=np.uint8),
				bitorder="little",
			)
			result[local_row] = unpacked[
				bit_offset:bit_offset + width
			].astype(bool, copy=False)

	return result


def internal_sea_contact(land, sea):
	if land.shape[1] > 1:
		if np.any(land[:, 1:] & (sea[:, :-1] != 0)):
			return True
		if np.any(land[:, :-1] & (sea[:, 1:] != 0)):
			return True

	if land.shape[0] > 1:
		if np.any(land[1:, :] & (sea[:-1, :] != 0)):
			return True
		if np.any(land[:-1, :] & (sea[1:, :] != 0)):
			return True

	return False


def improve(target, values):
	better = values < target
	count = int(np.count_nonzero(better))
	if count:
		target[better] = values[better]
	return count


def initialize_output(path, cells, sentinel, chunk_cells=1 << 20):
	path = Path(path)
	path.parent.mkdir(parents=True, exist_ok=True)

	chunk = np.full(
		min(chunk_cells, cells),
		sentinel,
		dtype=np.uint8,
	)

	with path.open("wb") as output:
		remaining = int(cells)
		while remaining:
			count = min(remaining, chunk.size)
			output.write(chunk[:count].tobytes())
			remaining -= count


def process_domains(
	elevation_path,
	sea_mask_path,
	land_mask_path,
	output_path,
	work_dir,
	solver_path,
	levels_csv,
	*,
	width,
	height,
	domain_width,
	domain_height,
	max_solver_runs=100000,
):
	width = int(width)
	height = int(height)
	domain_width = int(domain_width)
	domain_height = int(domain_height)
	max_solver_runs = int(max_solver_runs)

	if width <= 0 or height <= 0:
		raise ValueError("width und height müssen > 0 sein.")
	if domain_width <= 0 or domain_height <= 0:
		raise ValueError(
			"domain_width und domain_height müssen > 0 sein."
		)
	if max_solver_runs <= 0:
		raise ValueError("max_solver_runs muss > 0 sein.")

	cell_count = width * height
	require_file_size(
		elevation_path,
		cell_count * np.dtype(np.float32).itemsize,
	)
	require_file_size(
		sea_mask_path,
		cell_count * np.dtype(np.uint8).itemsize,
	)
	require_file_size(
		land_mask_path,
		(cell_count + 7) // 8,
	)

	levels = [
		value
		for value in levels_csv.split(",")
		if value
	]
	sentinel = len(levels)
	if sentinel <= 0 or sentinel > 254:
		raise ValueError("Ungültige Threshold-Klassen.")

	work_dir = Path(work_dir)
	shutil.rmtree(work_dir, ignore_errors=True)
	work_dir.mkdir(parents=True, exist_ok=True)

	domains = {}
	total_land_cells = 0

	for grid_row, y0 in enumerate(
		range(0, height, domain_height)
	):
		local_height = min(domain_height, height - y0)

		for grid_col, x0 in enumerate(
			range(0, width, domain_width)
		):
			local_width = min(domain_width, width - x0)
			land = read_packed_window(
				land_mask_path,
				source_width=width,
				x0=x0,
				y0=y0,
				width=local_width,
				height=local_height,
			)
			land_cells = int(np.count_nonzero(land))
			if land_cells == 0:
				continue

			elevation = read_window(
				elevation_path,
				dtype=np.float32,
				source_width=width,
				x0=x0,
				y0=y0,
				width=local_width,
				height=local_height,
			)
			sea = read_window(
				sea_mask_path,
				dtype=np.uint8,
				source_width=width,
				x0=x0,
				y0=y0,
				width=local_width,
				height=local_height,
			)

			elevation[~land] = np.nan

			domain_dir = (
				work_dir
				/ f"r{grid_row}-c{grid_col}"
			)
			domain_dir.mkdir(parents=True)

			elevation_path_local = (
				domain_dir / "elevation.f32"
			)
			sea_path_local = (
				domain_dir / "sea.u8"
			)
			land_path_local = (
				domain_dir / "land.u8"
			)

			elevation.tofile(elevation_path_local)
			sea.tofile(sea_path_local)
			land.astype(np.uint8).tofile(
				land_path_local
			)

			incoming = {
				"top": np.full(
					local_width,
					sentinel,
					dtype=np.uint8,
				),
				"bottom": np.full(
					local_width,
					sentinel,
					dtype=np.uint8,
				),
				"left": np.full(
					local_height,
					sentinel,
					dtype=np.uint8,
				),
				"right": np.full(
					local_height,
					sentinel,
					dtype=np.uint8,
				),
			}

			if y0 > 0:
				outside = read_window(
					sea_mask_path,
					dtype=np.uint8,
					source_width=width,
					x0=x0,
					y0=y0 - 1,
					width=local_width,
					height=1,
				)[0]
				incoming["top"][
					land[0] & (outside != 0)
				] = 0

			if y0 + local_height < height:
				outside = read_window(
					sea_mask_path,
					dtype=np.uint8,
					source_width=width,
					x0=x0,
					y0=y0 + local_height,
					width=local_width,
					height=1,
				)[0]
				incoming["bottom"][
					land[-1] & (outside != 0)
				] = 0

			if x0 > 0:
				outside = read_window(
					sea_mask_path,
					dtype=np.uint8,
					source_width=width,
					x0=x0 - 1,
					y0=y0,
					width=1,
					height=local_height,
				)[:, 0]
				incoming["left"][
					land[:, 0] & (outside != 0)
				] = 0

			if x0 + local_width < width:
				outside = read_window(
					sea_mask_path,
					dtype=np.uint8,
					source_width=width,
					x0=x0 + local_width,
					y0=y0,
					width=1,
					height=local_height,
				)[:, 0]
				incoming["right"][
					land[:, -1] & (outside != 0)
				] = 0

			key = (grid_row, grid_col)
			domains[key] = {
				"key": key,
				"x0": x0,
				"y0": y0,
				"width": local_width,
				"height": local_height,
				"cells": local_width * local_height,
				"land_cells": land_cells,
				"dir": domain_dir,
				"elevation_path": elevation_path_local,
				"sea_path": sea_path_local,
				"land_path": land_path_local,
				"boundary_path": (
					domain_dir / "boundary.u8"
				),
				"output_path": (
					domain_dir / "threshold.u8"
				),
				"incoming": incoming,
				"internal_sea_contact": (
					internal_sea_contact(land, sea)
				),
				"runs": 0,
			}
			total_land_cells += land_cells

	if not domains and total_land_cells == 0:
		initialize_output(
			output_path,
			cell_count,
			sentinel,
		)
		return {
			"domain_count": 0,
			"land_cells": 0,
			"solver_runs": 0,
			"boundary_improvements": 0,
			"max_domain_runs": 0,
			"sentinel_class": sentinel,
		}

	def has_boundary_seed(domain):
		return any(
			np.any(values < sentinel)
			for values in domain["incoming"].values()
		)

	queue = deque()
	queued = set()

	for key, domain in domains.items():
		if (
			domain["internal_sea_contact"]
			or has_boundary_seed(domain)
		):
			queue.append(key)
			queued.add(key)

	solver_runs = 0
	boundary_improvements = 0

	def queue_domain(key):
		if key not in domains or key in queued:
			return
		queue.append(key)
		queued.add(key)

	def write_boundary(domain):
		boundary = np.full(
			(domain["height"], domain["width"]),
			sentinel,
			dtype=np.uint8,
		)
		boundary[0, :] = np.minimum(
			boundary[0, :],
			domain["incoming"]["top"],
		)
		boundary[-1, :] = np.minimum(
			boundary[-1, :],
			domain["incoming"]["bottom"],
		)
		boundary[:, 0] = np.minimum(
			boundary[:, 0],
			domain["incoming"]["left"],
		)
		boundary[:, -1] = np.minimum(
			boundary[:, -1],
			domain["incoming"]["right"],
		)
		boundary.tofile(domain["boundary_path"])

	while queue:
		key = queue.popleft()
		queued.remove(key)
		domain = domains[key]

		solver_runs += 1
		if solver_runs > max_solver_runs:
			raise RuntimeError(
				"Domain-Solver hat max_solver_runs "
				"überschritten."
			)

		write_boundary(domain)

		subprocess.run([
			str(solver_path),
			"--elevation",
			str(domain["elevation_path"]),
			"--sea-mask",
			str(domain["sea_path"]),
			"--boundary-threshold",
			str(domain["boundary_path"]),
			"--output",
			str(domain["output_path"]),
			"--width",
			str(domain["width"]),
			"--height",
			str(domain["height"]),
			"--levels",
			levels_csv,
			"--connectivity",
			"4",
		], check=True)

		domain["runs"] += 1

		result = np.fromfile(
			domain["output_path"],
			dtype=np.uint8,
		).reshape(
			(domain["height"], domain["width"])
		)
		land = np.fromfile(
			domain["land_path"],
			dtype=np.uint8,
		).reshape(
			(domain["height"], domain["width"])
		) != 0

		grid_row, grid_col = key
		neighbors = [
			(
				(grid_row - 1, grid_col),
				"bottom",
				result[0, :],
				land[0, :],
			),
			(
				(grid_row + 1, grid_col),
				"top",
				result[-1, :],
				land[-1, :],
			),
			(
				(grid_row, grid_col - 1),
				"right",
				result[:, 0],
				land[:, 0],
			),
			(
				(grid_row, grid_col + 1),
				"left",
				result[:, -1],
				land[:, -1],
			),
		]

		for (
			neighbor_key,
			neighbor_side,
			values,
			edge_land,
		) in neighbors:
			neighbor = domains.get(neighbor_key)
			if neighbor is None:
				continue

			outgoing = np.full(
				values.shape,
				sentinel,
				dtype=np.uint8,
			)
			valid = (
				edge_land
				& (values < sentinel)
			)
			outgoing[valid] = values[valid]

			changed = improve(
				neighbor["incoming"][neighbor_side],
				outgoing,
			)
			if changed:
				boundary_improvements += changed
				queue_domain(neighbor_key)

	initialize_output(
		output_path,
		cell_count,
		sentinel,
	)

	unsolved_land_cells = 0

	with Path(output_path).open("r+b") as output:
		for domain in domains.values():
			if not domain["output_path"].exists():
				unsolved_land_cells += domain["land_cells"]
				continue

			result = np.fromfile(
				domain["output_path"],
				dtype=np.uint8,
			).reshape(
				(domain["height"], domain["width"])
			)
			land = np.fromfile(
				domain["land_path"],
				dtype=np.uint8,
			).reshape(
				(domain["height"], domain["width"])
			) != 0

			unsolved_land_cells += int(
				np.count_nonzero(
					land & (result >= sentinel)
				)
			)

			for local_row in range(domain["height"]):
				values = np.full(
					domain["width"],
					sentinel,
					dtype=np.uint8,
				)
				row_land = land[local_row]
				values[row_land] = result[
					local_row,
					row_land,
				]

				global_row = domain["y0"] + local_row
				offset = (
					global_row * width
					+ domain["x0"]
				)
				output.seek(offset)
				output.write(values.tobytes())

	if unsolved_land_cells:
		raise RuntimeError(
			f"{unsolved_land_cells} Landzellen blieben "
			"nach der Domain-Konvergenz ungelöst."
		)

	return {
		"domain_count": len(domains),
		"land_cells": total_land_cells,
		"solver_runs": solver_runs,
		"boundary_improvements": boundary_improvements,
		"max_domain_runs": max(
			domain["runs"]
			for domain in domains.values()
		),
		"sentinel_class": sentinel,
		"domain_width": domain_width,
		"domain_height": domain_height,
		"domains": [
			{
				"grid_row": domain["key"][0],
				"grid_col": domain["key"][1],
				"x0": domain["x0"],
				"y0": domain["y0"],
				"width": domain["width"],
				"height": domain["height"],
				"land_cells": domain["land_cells"],
				"runs": domain["runs"],
			}
			for domain in domains.values()
		],
	}


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--elevation", required=True)
	parser.add_argument("--sea-mask", required=True)
	parser.add_argument("--land-mask", required=True)
	parser.add_argument("--output", required=True)
	parser.add_argument("--work-dir", required=True)
	parser.add_argument("--solver", required=True)
	parser.add_argument("--levels", required=True)
	parser.add_argument("--width", type=int, required=True)
	parser.add_argument("--height", type=int, required=True)
	parser.add_argument("--domain-width", type=int, required=True)
	parser.add_argument("--domain-height", type=int, required=True)
	parser.add_argument(
		"--max-solver-runs",
		type=int,
		default=100000,
	)
	parser.add_argument("--report")
	args = parser.parse_args()

	result = process_domains(
		args.elevation,
		args.sea_mask,
		args.land_mask,
		args.output,
		args.work_dir,
		args.solver,
		args.levels,
		width=args.width,
		height=args.height,
		domain_width=args.domain_width,
		domain_height=args.domain_height,
		max_solver_runs=args.max_solver_runs,
	)

	if args.report:
		Path(args.report).write_text(
			json.dumps(result, indent=2) + "\n",
			encoding="utf-8",
		)

	print(json.dumps(result, indent=2))


if __name__ == "__main__":
	main()
