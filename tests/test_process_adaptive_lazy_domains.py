#!/usr/bin/env python3

import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from process_adaptive_lazy_domains import (
	build_adjacencies,
	process_adaptive_lazy_domains,
	resample_thresholds,
)


LEVELS = "0,1,2,3,4,5,6"


def test_internal_external_sea_is_ignored(tmp):
	domains = [
		{
			"id": 1,
			"zoom": 0,
			"coarse_x0": 0,
			"coarse_y0": 0,
			"coarse_width": 1,
			"coarse_height": 1,
			"fine_pixels_per_coarse_cell": 1,
			"fine_width": 1,
			"fine_height": 1,
		},
		{
			"id": 2,
			"zoom": 1,
			"coarse_x0": 1,
			"coarse_y0": 0,
			"coarse_width": 1,
			"coarse_height": 1,
			"fine_pixels_per_coarse_cell": 2,
			"fine_width": 2,
			"fine_height": 2,
		},
	]

	def materialize(domain, domain_dir):
		height = int(domain["fine_height"])
		width = int(domain["fine_width"])
		elevation_path = domain_dir / "elevation.f32"
		sea_path = domain_dir / "sea.u8"
		land_path = domain_dir / "land.u8"

		np.ones(
			(height, width),
			dtype=np.float32,
		).tofile(elevation_path)
		np.zeros(
			(height, width),
			dtype=np.uint8,
		).tofile(sea_path)
		np.ones(
			(height, width),
			dtype=np.uint8,
		).tofile(land_path)

		external = {
			"top": np.zeros(width, dtype=bool),
			"bottom": np.zeros(width, dtype=bool),
			"left": np.zeros(height, dtype=bool),
			"right": np.zeros(height, dtype=bool),
		}
		if int(domain["id"]) == 1:
			external["right"][:] = True
		else:
			external["left"][:] = True

		return {
			"elevation_path": str(elevation_path),
			"sea_mask_path": str(sea_path),
			"land_mask_path": str(land_path),
			"external_sea": external,
		}

	report = process_adaptive_lazy_domains(
		domains,
		materialize,
		tmp / "internal-output",
		tmp / "internal-work",
		ROOT / "build" / "priority_flood_quantized",
		LEVELS,
	)

	sentinel = len(LEVELS.split(","))
	for path, shape in (
		(tmp / "internal-output/r1-c0.u8", (1, 1)),
		(tmp / "internal-output/r2-c1.u8", (2, 2)),
	):
		values = np.fromfile(
			path,
			dtype=np.uint8,
		).reshape(shape)
		if np.any(values != sentinel):
			raise AssertionError(
				"Sea außerhalb einer internen Domainkante "
				"darf nicht als externer Seed wirken."
			)

	if report["external_sea_improvements"] != 0:
		raise AssertionError(report)
	if (
		report[
			"internal_edge_pixels_excluded_from_external_sea"
		]
		!= 3
	):
		raise AssertionError(report)


def main():
	domain_specs = [
		{
			"id": 1,
			"zoom": 0,
			"coarse_x0": 0,
			"coarse_y0": 0,
			"coarse_width": 1,
			"coarse_height": 1,
			"fine_pixels_per_coarse_cell": 1,
			"fine_width": 1,
			"fine_height": 1,
		},
		{
			"id": 2,
			"zoom": 1,
			"coarse_x0": 1,
			"coarse_y0": 0,
			"coarse_width": 1,
			"coarse_height": 1,
			"fine_pixels_per_coarse_cell": 2,
			"fine_width": 2,
			"fine_height": 2,
		},
		{
			"id": 3,
			"zoom": 0,
			"coarse_x0": 2,
			"coarse_y0": 0,
			"coarse_width": 1,
			"coarse_height": 1,
			"fine_pixels_per_coarse_cell": 1,
			"fine_width": 1,
			"fine_height": 1,
		},
	]

	data = {
		1: {
			"elevation": np.asarray(
				[[4.0]],
				dtype=np.float32,
			),
			"sea": np.asarray(
				[[0]],
				dtype=np.uint8,
			),
		},
		2: {
			"elevation": np.asarray(
				[
					[2.0, 3.0],
					[1.0, 5.0],
				],
				dtype=np.float32,
			),
			"sea": np.zeros(
				(2, 2),
				dtype=np.uint8,
			),
		},
		3: {
			"elevation": np.asarray(
				[[0.0]],
				dtype=np.float32,
			),
			"sea": np.asarray(
				[[1]],
				dtype=np.uint8,
			),
		},
	}

	# Die direkte Resampling-Regel selbst explizit absichern.
	fine = np.asarray([5, 3, 4, 6], dtype=np.uint8)
	reduced = resample_thresholds(
		fine,
		2,
		1,
		7,
	)
	if reduced.tolist() != [3, 4]:
		raise AssertionError(reduced)
	repeated = resample_thresholds(
		np.asarray([2, 5], dtype=np.uint8),
		1,
		2,
		7,
	)
	if repeated.tolist() != [2, 2, 5, 5]:
		raise AssertionError(repeated)

	domain_map = {
		item["id"]: {
			**item,
			"width": item["fine_width"],
			"height": item["fine_height"],
		}
		for item in domain_specs
	}
	adjacencies, _ = build_adjacencies(domain_map)
	if len(adjacencies) != 2:
		raise AssertionError(adjacencies)

	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		test_internal_external_sea_is_ignored(tmp)
		output_dir = tmp / "output"
		work_dir = tmp / "work"

		def materialize(domain, domain_dir):
			item = data[int(domain["id"])]
			elevation_path = (
				domain_dir / "elevation.f32"
			)
			sea_path = domain_dir / "sea.u8"
			land_path = domain_dir / "land.u8"

			item["elevation"].tofile(elevation_path)
			item["sea"].tofile(sea_path)
			np.ones(
				item["sea"].shape,
				dtype=np.uint8,
			).tofile(land_path)

			return {
				"elevation_path": str(elevation_path),
				"sea_mask_path": str(sea_path),
				"land_mask_path": str(land_path),
			}

		report = process_adaptive_lazy_domains(
			domain_specs,
			materialize,
			output_dir,
			work_dir,
			ROOT / "build" / "priority_flood_quantized",
			LEVELS,
		)

		left = np.fromfile(
			output_dir / "r1-c0.u8",
			dtype=np.uint8,
		).reshape((1, 1))
		middle = np.fromfile(
			output_dir / "r2-c1.u8",
			dtype=np.uint8,
		).reshape((2, 2))
		right = np.fromfile(
			output_dir / "r3-c0.u8",
			dtype=np.uint8,
		).reshape((1, 1))

		if right.tolist() != [[0]]:
			raise AssertionError(right)
		if middle.tolist() != [
			[3, 3],
			[3, 5],
		]:
			raise AssertionError(middle)
		if left.tolist() != [[4]]:
			raise AssertionError(left)

		if report["domain_count"] != 3:
			raise AssertionError(report)
		if report["adjacency_count"] != 2:
			raise AssertionError(report)
		if report["solver_runs"] <= 3:
			raise AssertionError(
				"Seedlose Domains müssen nach späteren "
				"Randverbesserungen erneut gerechnet werden."
			)
		if report["boundary_improvements"] <= 0:
			raise AssertionError(report)
		if report["peak_materialized_cells"] != 4:
			raise AssertionError(report)
		if not report["all_domain_work_deleted"]:
			raise AssertionError(report)

		seeded_output = tmp / "seeded-output"
		seeded = process_adaptive_lazy_domains(
			domain_specs,
			materialize,
			seeded_output,
			tmp / "seeded-work",
			ROOT / "build" / "priority_flood_quantized",
			LEVELS,
			initial_domain_ids=[3],
		)
		if seeded["initial_domain_count"] != 1:
			raise AssertionError(seeded)
		if seeded["solver_runs"] > report["solver_runs"]:
			raise AssertionError(
				"Seeded Queue darf nicht mehr Solver-Runs "
				"als der All-Domain-Start benötigen."
			)
		for name, shape in (
			("r1-c0.u8", (1, 1)),
			("r2-c1.u8", (2, 2)),
			("r3-c0.u8", (1, 1)),
		):
			expected = np.fromfile(
				output_dir / name,
				dtype=np.uint8,
			).reshape(shape)
			actual = np.fromfile(
				seeded_output / name,
				dtype=np.uint8,
			).reshape(shape)
			if not np.array_equal(expected, actual):
				raise AssertionError(
					f"Seeded Queue weicht für {name} ab."
				)

		missed_seed_raised = False
		try:
			process_adaptive_lazy_domains(
				domain_specs,
				materialize,
				tmp / "missed-seed-output",
				tmp / "missed-seed-work",
				ROOT / "build" / "priority_flood_quantized",
				LEVELS,
				initial_domain_ids=[1],
				write_outputs_during_convergence=False,
			)
		except RuntimeError as error:
			if "Seed-Plan unvollständig" not in str(error):
				raise
			missed_seed_raised = True

		if not missed_seed_raised:
			raise AssertionError(
				"Finalisierung muss einen übersehenen "
				"Sea-Seed ablehnen."
			)

		checkpoint_path = tmp / "adaptive-checkpoint.npz"
		resume_output = tmp / "resume-output"
		resume_work = tmp / "resume-work"

		paused = process_adaptive_lazy_domains(
			domain_specs,
			materialize,
			resume_output,
			resume_work,
			ROOT / "build" / "priority_flood_quantized",
			LEVELS,
			checkpoint_path=checkpoint_path,
			checkpoint_every_runs=1,
			max_runs_this_invocation=2,
			write_outputs_during_convergence=False,
		)
		if paused["status"] != "paused":
			raise AssertionError(paused)
		if paused["completed"]:
			raise AssertionError(paused)
		if paused["queue_remaining"] <= 0:
			raise AssertionError(paused)
		if not checkpoint_path.exists():
			raise AssertionError(
				"Checkpoint wurde nicht geschrieben."
			)
		if list(resume_output.glob("*.u8")):
			raise AssertionError(
				"Während der checkpointbaren Konvergenz "
				"darf noch keine Endausgabe geschrieben werden."
			)

		resumed = process_adaptive_lazy_domains(
			domain_specs,
			materialize,
			resume_output,
			resume_work,
			ROOT / "build" / "priority_flood_quantized",
			LEVELS,
			checkpoint_path=checkpoint_path,
			checkpoint_every_runs=1,
			resume=True,
			write_outputs_during_convergence=False,
		)
		if resumed["status"] != "complete":
			raise AssertionError(resumed)
		if not resumed["completed"]:
			raise AssertionError(resumed)
		if resumed["queue_remaining"] != 0:
			raise AssertionError(resumed)
		if resumed["finalization_materializations"] != 3:
			raise AssertionError(resumed)
		if not resumed["all_domain_work_deleted"]:
			raise AssertionError(resumed)

		for name, shape in (
			("r1-c0.u8", (1, 1)),
			("r2-c1.u8", (2, 2)),
			("r3-c0.u8", (1, 1)),
		):
			expected = np.fromfile(
				output_dir / name,
				dtype=np.uint8,
			).reshape(shape)
			actual = np.fromfile(
				resume_output / name,
				dtype=np.uint8,
			).reshape(shape)
			if not np.array_equal(expected, actual):
				raise AssertionError(
					f"Resume-Ausgabe weicht für {name} ab."
				)

	print("ok")


if __name__ == "__main__":
	main()
