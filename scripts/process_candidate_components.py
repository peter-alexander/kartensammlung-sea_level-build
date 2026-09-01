#!/usr/bin/env python3

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from materialize_candidate_component import materialize


SPAN_RECORD_BYTES = 12


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


def read_component_spans(spans_path, component):
	offset_records = int(component["span_offset_records"])
	span_count = int(component["span_count"])

	with Path(spans_path).open("rb") as source:
		source.seek(offset_records * SPAN_RECORD_BYTES)
		raw = source.read(span_count * SPAN_RECORD_BYTES)

	if len(raw) != span_count * SPAN_RECORD_BYTES:
		raise RuntimeError(
			"Span-Datei endet innerhalb der Komponente."
		)

	return np.frombuffer(
		raw,
		dtype="<u4",
	).reshape((-1, 3))


def scatter_component(
	output_path,
	local_threshold_path,
	component_meta,
	spans,
):
	window = component_meta["window"]
	x0 = int(window["x0"])
	y0 = int(window["y0"])
	local_width = int(window["width"])
	local_height = int(window["height"])
	global_width = int(component_meta["global_width"])

	local = np.memmap(
		local_threshold_path,
		dtype=np.uint8,
		mode="r",
		shape=(local_height, local_width),
	)

	with Path(output_path).open("r+b") as output:
		for row, left, right in spans:
			row = int(row)
			left = int(left)
			right = int(right)

			local_row = row - y0
			local_left = left - x0
			local_right = right - x0

			if (
				local_row < 0
				or local_row >= local_height
				or local_left < 0
				or local_right >= local_width
			):
				raise RuntimeError(
					"Span liegt außerhalb des lokalen "
					"Component-Fensters."
				)

			values = np.asarray(
				local[
					local_row,
					local_left:local_right + 1,
				],
				dtype=np.uint8,
			)

			global_offset = row * global_width + left
			output.seek(global_offset)
			output.write(values.tobytes())

	del local


def solve_direct(
	solver_path,
	component_dir,
	local_threshold,
	meta,
	levels_csv,
):
	subprocess.run([
		str(solver_path),
		"--elevation",
		str(component_dir / "elevation.f32"),
		"--sea-mask",
		str(component_dir / "sea_mask.u8"),
		"--land-mask",
		str(component_dir / "land_mask.bit"),
		"--output",
		str(local_threshold),
		"--width",
		str(meta["window"]["width"]),
		"--height",
		str(meta["window"]["height"]),
		"--levels",
		levels_csv,
	], check=True)


def solve_split(
	domain_solver_path,
	component_dir,
	local_threshold,
	meta,
	levels_csv,
	*,
	domain_width,
	domain_height,
	domain_max_solver_runs,
):
	report_path = component_dir / "domain-report.json"
	script_path = (
		Path(__file__).resolve().with_name(
			"process_component_domains.py"
		)
	)

	subprocess.run([
		sys.executable,
		str(script_path),
		"--elevation",
		str(component_dir / "elevation.f32"),
		"--sea-mask",
		str(component_dir / "sea_mask.u8"),
		"--land-mask",
		str(component_dir / "land_mask.bit"),
		"--output",
		str(local_threshold),
		"--work-dir",
		str(component_dir / "domains"),
		"--solver",
		str(domain_solver_path),
		"--levels",
		levels_csv,
		"--width",
		str(meta["window"]["width"]),
		"--height",
		str(meta["window"]["height"]),
		"--domain-width",
		str(domain_width),
		"--domain-height",
		str(domain_height),
		"--max-solver-runs",
		str(domain_max_solver_runs),
		"--report",
		str(report_path),
	], check=True, stdout=subprocess.DEVNULL)

	return json.loads(report_path.read_text())


def process_components(
	components_report_path,
	spans_path,
	elevation_path,
	sea_mask_path,
	output_path,
	work_dir,
	solver_path,
	levels_csv,
	*,
	global_width,
	global_height,
	halo=1,
	component_ids=None,
	max_direct_window_cells=0,
	domain_solver_path=None,
	domain_width=2048,
	domain_height=2048,
	domain_max_solver_runs=100000,
):
	report = json.loads(
		Path(components_report_path).read_text()
	)
	components = report["components"]

	if component_ids is not None:
		wanted = {
			int(component_id)
			for component_id in component_ids
		}
		components = [
			component
			for component in components
			if int(component["id"]) in wanted
		]
		found = {
			int(component["id"])
			for component in components
		}
		missing = wanted - found
		if missing:
			raise ValueError(
				f"Unbekannte Component-IDs: {sorted(missing)}"
			)

	max_direct_window_cells = int(max_direct_window_cells)
	domain_width = int(domain_width)
	domain_height = int(domain_height)
	domain_max_solver_runs = int(domain_max_solver_runs)

	if max_direct_window_cells < 0:
		raise ValueError(
			"max_direct_window_cells muss >= 0 sein."
		)
	if domain_width <= 0 or domain_height <= 0:
		raise ValueError(
			"domain_width und domain_height müssen > 0 sein."
		)
	if domain_max_solver_runs <= 0:
		raise ValueError(
			"domain_max_solver_runs muss > 0 sein."
		)

	sentinel = len(
		[
			value
			for value in levels_csv.split(",")
			if value
		]
	)
	if sentinel <= 0 or sentinel > 254:
		raise ValueError("Ungültige Threshold-Klassen.")

	global_cells = int(global_width) * int(global_height)
	initialize_output(
		output_path,
		global_cells,
		sentinel,
	)

	work_dir = Path(work_dir)
	work_dir.mkdir(parents=True, exist_ok=True)

	processed_cells = 0
	processed_components = 0
	peak_local_window_cells = 0
	direct_components = 0
	split_components = 0
	split_solver_runs = 0
	split_domain_count = 0
	split_boundary_improvements = 0
	max_split_domain_runs = 0

	for component in components:
		component_id = int(component["id"])
		component_dir = (
			work_dir
			/ f"component-{component_id}"
		)

		try:
			meta = materialize(
				components_report_path,
				spans_path,
				component_id,
				elevation_path,
				sea_mask_path,
				component_dir,
				global_width=global_width,
				global_height=global_height,
				halo=halo,
			)

			local_threshold = (
				component_dir
				/ "threshold.u8"
			)
			window_cells = int(
				meta["window"]["cells"]
			)
			use_split = (
				max_direct_window_cells > 0
				and window_cells
					> max_direct_window_cells
			)

			if use_split:
				if domain_solver_path is None:
					raise ValueError(
						"Component überschreitet "
						"max_direct_window_cells, aber "
						"domain_solver_path fehlt."
					)

				domain_report = solve_split(
					domain_solver_path,
					component_dir,
					local_threshold,
					meta,
					levels_csv,
					domain_width=domain_width,
					domain_height=domain_height,
					domain_max_solver_runs=(
						domain_max_solver_runs
					),
				)
				split_components += 1
				split_solver_runs += int(
					domain_report["solver_runs"]
				)
				split_domain_count += int(
					domain_report["domain_count"]
				)
				split_boundary_improvements += int(
					domain_report[
						"boundary_improvements"
					]
				)
				max_split_domain_runs = max(
					max_split_domain_runs,
					int(
						domain_report[
							"max_domain_runs"
						]
					),
				)
			else:
				solve_direct(
					solver_path,
					component_dir,
					local_threshold,
					meta,
					levels_csv,
				)
				direct_components += 1

			spans = read_component_spans(
				spans_path,
				component,
			)
			scatter_component(
				output_path,
				local_threshold,
				meta,
				spans,
			)

			processed_cells += int(
				component["cells"]
			)
			processed_components += 1
			peak_local_window_cells = max(
				peak_local_window_cells,
				window_cells,
			)
		finally:
			shutil.rmtree(
				component_dir,
				ignore_errors=True,
			)

	return {
		"processed_components": processed_components,
		"processed_cells": processed_cells,
		"peak_local_window_cells": peak_local_window_cells,
		"sentinel_class": sentinel,
		"max_direct_window_cells": max_direct_window_cells,
		"direct_components": direct_components,
		"split_components": split_components,
		"split_domain_count": split_domain_count,
		"split_solver_runs": split_solver_runs,
		"split_boundary_improvements": (
			split_boundary_improvements
		),
		"max_split_domain_runs": max_split_domain_runs,
		"domain_width": domain_width,
		"domain_height": domain_height,
	}


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--components-report", required=True)
	parser.add_argument("--spans", required=True)
	parser.add_argument("--elevation", required=True)
	parser.add_argument("--sea-mask", required=True)
	parser.add_argument("--output", required=True)
	parser.add_argument("--work-dir", required=True)
	parser.add_argument("--solver", required=True)
	parser.add_argument("--levels", required=True)
	parser.add_argument("--global-width", type=int, required=True)
	parser.add_argument("--global-height", type=int, required=True)
	parser.add_argument("--halo", type=int, default=1)
	parser.add_argument(
		"--component-id",
		type=int,
		action="append",
		dest="component_ids",
	)
	parser.add_argument(
		"--max-direct-window-cells",
		type=int,
		default=0,
		help=(
			"0 deaktiviert den Domain-Fallback. Größere "
			"Component-Fenster werden sonst gesplittet."
		),
	)
	parser.add_argument("--domain-solver")
	parser.add_argument(
		"--domain-width",
		type=int,
		default=2048,
	)
	parser.add_argument(
		"--domain-height",
		type=int,
		default=2048,
	)
	parser.add_argument(
		"--domain-max-solver-runs",
		type=int,
		default=100000,
	)
	args = parser.parse_args()

	result = process_components(
		args.components_report,
		args.spans,
		args.elevation,
		args.sea_mask,
		args.output,
		args.work_dir,
		args.solver,
		args.levels,
		global_width=args.global_width,
		global_height=args.global_height,
		halo=args.halo,
		component_ids=args.component_ids,
		max_direct_window_cells=(
			args.max_direct_window_cells
		),
		domain_solver_path=args.domain_solver,
		domain_width=args.domain_width,
		domain_height=args.domain_height,
		domain_max_solver_runs=(
			args.domain_max_solver_runs
		),
	)

	print(json.dumps(result, indent=2))


if __name__ == "__main__":
	main()
