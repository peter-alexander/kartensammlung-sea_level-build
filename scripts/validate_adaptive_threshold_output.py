#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import numpy as np

from process_adaptive_lazy_domains import (
	build_adjacencies,
	checkpoint_signature,
	load_checkpoint,
	resample_thresholds,
	side_offset,
)


SIDES = ("top", "bottom", "left", "right")


def normalized_domains(plan, sentinel):
	result = {}
	for index, source in enumerate(plan["domains"], start=1):
		domain = {
			**source,
			"id": int(source.get("id", index)),
		}
		key = int(domain["id"])
		if key in result:
			raise AssertionError(f"Doppelte Domain-ID {key}.")
		width = int(domain["fine_width"])
		height = int(domain["fine_height"])
		domain.update({
			"width": width,
			"height": height,
			"incoming": {
				"top": np.full(width, sentinel, dtype=np.uint8),
				"bottom": np.full(width, sentinel, dtype=np.uint8),
				"left": np.full(height, sentinel, dtype=np.uint8),
				"right": np.full(height, sentinel, dtype=np.uint8),
			},
			"runs": 0,
			"land_cells": None,
		})
		result[key] = domain
	return result


def threshold_path(threshold_dir, domain):
	return (
		Path(threshold_dir)
		/ f"r{int(domain['id'])}-c{int(domain['zoom'])}.u8"
	)


def threshold_array(threshold_dir, domain):
	return np.memmap(
		threshold_path(threshold_dir, domain),
		dtype=np.uint8,
		mode="r",
		shape=(
			int(domain["fine_height"]),
			int(domain["fine_width"]),
		),
	)


def edge(array, side):
	if side == "top":
		return array[0, :]
	if side == "bottom":
		return array[-1, :]
	if side == "left":
		return array[:, 0]
	if side == "right":
		return array[:, -1]
	raise ValueError(f"Unbekannte Seite: {side}")


def validate_checkpoint(domains, checkpoint_path, levels_csv):
	signature = checkpoint_signature(
		[
			{
				**domain,
				"id": int(domain["id"]),
			}
			for domain in sorted(
				domains.values(),
				key=lambda item: int(item["id"]),
			)
		],
		levels_csv,
	)
	state = load_checkpoint(
		checkpoint_path,
		domains,
		expected_signature=signature,
	)
	if not state["completed"]:
		raise AssertionError("Checkpoint ist nicht completed.")
	if state["queue"]:
		raise AssertionError("Completed-Checkpoint enthält noch Queue-Einträge.")
	if any(
		domain["land_cells"] is None
		for domain in domains.values()
	):
		raise AssertionError(
			"Completed-Checkpoint enthält unbekannte Land-Cell-Zahlen."
		)
	return {
		"signature": signature,
		"counters": state["counters"],
	}


def validate_files(domains, threshold_dir, sentinel):
	threshold_dir = Path(threshold_dir)
	expected = {
		threshold_path(threshold_dir, domain).name: (
			int(domain["fine_width"])
			* int(domain["fine_height"])
		)
		for domain in domains.values()
	}
	actual = {
		path.name: path.stat().st_size
		for path in threshold_dir.glob("*.u8")
	}
	missing = sorted(set(expected) - set(actual))
	unexpected = sorted(set(actual) - set(expected))
	wrong_sizes = sorted(
		name
		for name in set(expected) & set(actual)
		if expected[name] != actual[name]
	)
	if missing or unexpected or wrong_sizes:
		raise AssertionError({
			"missing": missing[:20],
			"unexpected": unexpected[:20],
			"wrong_sizes": wrong_sizes[:20],
		})

	histogram = np.zeros(sentinel + 1, dtype=np.int64)
	by_zoom = {}
	zero_run_domains = 0
	zero_run_cells = 0

	for domain in domains.values():
		values = threshold_array(threshold_dir, domain)
		max_value = int(np.max(values))
		if max_value > sentinel:
			raise AssertionError(
				f"Domain {domain['id']} enthält ungültige Klasse {max_value}."
			)
		counts = np.bincount(
			np.asarray(values).reshape(-1),
			minlength=sentinel + 1,
		)[:sentinel + 1]
		histogram += counts

		zoom = int(domain["zoom"])
		if zoom not in by_zoom:
			by_zoom[zoom] = np.zeros(
				sentinel + 1,
				dtype=np.int64,
			)
		by_zoom[zoom] += counts

		if int(domain["runs"]) == 0:
			zero_run_domains += 1
			zero_run_cells += int(values.size)
			non_sentinel = int(
				values.size - counts[sentinel]
			)
			if non_sentinel:
				raise AssertionError(
					f"Nie aktivierte Domain {domain['id']} "
					f"enthält {non_sentinel} Nicht-Sentinel-Zellen."
				)

	total = int(histogram.sum())
	return {
		"file_count": len(actual),
		"bytes": int(sum(actual.values())),
		"cells": total,
		"class_histogram": [int(value) for value in histogram],
		"sentinel_cells": int(histogram[sentinel]),
		"non_sentinel_cells": int(total - histogram[sentinel]),
		"zero_run_domain_count": zero_run_domains,
		"zero_run_cells": zero_run_cells,
		"zero_run_non_sentinel_cells": 0,
		"by_zoom": {
			str(zoom): {
				"cells": int(counts.sum()),
				"sentinel_cells": int(counts[sentinel]),
				"non_sentinel_cells": int(
					counts.sum() - counts[sentinel]
				),
			}
			for zoom, counts in sorted(by_zoom.items())
		},
	}


def validate_fixed_point(domains, threshold_dir, sentinel):
	adjacencies, _ = build_adjacencies(domains)
	improvable_pixels = 0
	improvable_segments = 0
	max_improvement = 0
	directed_checks = 0

	def check(
		source_key,
		source_side,
		target_key,
		target_side,
		coarse_start,
		coarse_end,
	):
		nonlocal directed_checks
		nonlocal improvable_pixels
		nonlocal improvable_segments
		nonlocal max_improvement

		directed_checks += 1
		source = domains[source_key]
		target = domains[target_key]
		source_values = edge(
			threshold_array(threshold_dir, source),
			source_side,
		)
		source_start = side_offset(
			source,
			source_side,
			coarse_start,
		)
		source_end = side_offset(
			source,
			source_side,
			coarse_end,
		)
		target_start = side_offset(
			target,
			target_side,
			coarse_start,
		)
		target_end = side_offset(
			target,
			target_side,
			coarse_end,
		)
		resampled = resample_thresholds(
			np.asarray(
				source_values[source_start:source_end],
				dtype=np.uint8,
			),
			source["fine_pixels_per_coarse_cell"],
			target["fine_pixels_per_coarse_cell"],
			sentinel,
		)
		target_values = target["incoming"][
			target_side
		][target_start:target_end]
		if resampled.size != target_values.size:
			raise AssertionError(
				"Resampelte Domain-Kante hat falsche Länge."
			)

		better = resampled < target_values
		count = int(np.count_nonzero(better))
		if count:
			improvable_segments += 1
			improvable_pixels += count
			max_improvement = max(
				max_improvement,
				int(np.max(
					target_values[better].astype(np.int16)
					- resampled[better].astype(np.int16)
				)),
			)

	for adjacency in adjacencies:
		check(
			adjacency["a"],
			adjacency["a_side"],
			adjacency["b"],
			adjacency["b_side"],
			adjacency["coarse_start"],
			adjacency["coarse_end"],
		)
		check(
			adjacency["b"],
			adjacency["b_side"],
			adjacency["a"],
			adjacency["a_side"],
			adjacency["coarse_start"],
			adjacency["coarse_end"],
		)

	if improvable_pixels:
		raise AssertionError({
			"message": "Threshold-Ausgabe ist kein Boundary-Fixpunkt.",
			"improvable_pixels": improvable_pixels,
			"improvable_segments": improvable_segments,
			"max_class_improvement": max_improvement,
		})
	return {
		"adjacency_count": len(adjacencies),
		"directed_edge_checks": directed_checks,
		"improvable_pixels": 0,
		"improvable_segments": 0,
		"max_class_improvement": 0,
	}


def component_spans(components_report_path, spans_path, component_id):
	report = json.loads(
		Path(components_report_path).read_text(encoding="utf-8")
	)
	component = next(
		(
			item
			for item in report["components"]
			if int(item["id"]) == int(component_id)
		),
		None,
	)
	if component is None:
		raise AssertionError(f"Component {component_id} fehlt.")
	if int(report.get("span_record_bytes", 12)) != 12:
		raise AssertionError("Unerwartete RLE-Recordgröße.")

	records = np.fromfile(spans_path, dtype="<u4")
	if records.size % 3:
		raise AssertionError("RLE-Datei hat ungültige Länge.")
	records = records.reshape((-1, 3))
	start = int(component["span_offset_records"])
	end = start + int(component["span_count"])
	if end > len(records):
		raise AssertionError("Component-RLE endet außerhalb der Span-Datei.")
	return report, component, records[start:end]


def validate_partition(plan, components_report_path, spans_path):
	report, component, spans = component_spans(
		components_report_path,
		spans_path,
		plan["component_id"],
	)
	width = int(report["width"])
	height = int(report["height"])
	expected = np.zeros((height, width), dtype=bool)
	span_cells = 0
	for row, left, right in spans:
		row = int(row)
		left = int(left)
		right = int(right)
		if not (
			0 <= row < height
			and 0 <= left <= right < width
		):
			raise AssertionError("Ungültiger Component-RLE-Span.")
		expected[row, left:right + 1] = True
		span_cells += right - left + 1
	if span_cells != int(component["cells"]):
		raise AssertionError("RLE-Zellzahl stimmt nicht mit Report überein.")

	coverage = np.zeros((height, width), dtype=np.uint16)
	for domain in plan["domains"]:
		x0 = int(domain["coarse_x0"])
		y0 = int(domain["coarse_y0"])
		x1 = x0 + int(domain["coarse_width"])
		y1 = y0 + int(domain["coarse_height"])
		if not (
			0 <= x0 < x1 <= width
			and 0 <= y0 < y1 <= height
		):
			raise AssertionError("Domain liegt außerhalb des Coarse-Rasters.")
		coverage[y0:y1, x0:x1] += 1

	result = {
		"component_id": int(component["id"]),
		"component_cells": int(component["cells"]),
		"covered_cells": int(np.count_nonzero(coverage)),
		"overlap_cells": int(np.count_nonzero(coverage > 1)),
		"missing_cells": int(
			np.count_nonzero(expected & (coverage == 0))
		),
		"extra_cells": int(
			np.count_nonzero((~expected) & (coverage > 0))
		),
		"span_count": int(component["span_count"]),
	}
	if any(
		result[key]
		for key in (
			"overlap_cells",
			"missing_cells",
			"extra_cells",
		)
	):
		raise AssertionError(result)
	if result["covered_cells"] != result["component_cells"]:
		raise AssertionError(result)
	return result


def reconstruction_manifest(
	plan,
	parent_grid_path,
	threshold_dir,
	levels_csv,
):
	grid = json.loads(
		Path(parent_grid_path).read_text(encoding="utf-8")
	)["grid"]
	parent_zoom = int(plan["parent_zoom"])
	if int(grid["zoom"]) != parent_zoom:
		raise AssertionError("Parent-Grid-Zoom passt nicht zum Plan.")

	tile_size = int(grid["tile_size"])
	coarse_factor = int(plan["coarse_factor"])
	parent_x0 = int(grid["x_min"]) * tile_size
	parent_y0 = int(grid["y_min"]) * tile_size
	domains = []

	for index, domain in enumerate(plan["domains"], start=1):
		domain_id = int(domain.get("id", index))
		zoom = int(domain["zoom"])
		scale = 1 << (zoom - parent_zoom)
		fine_per_coarse = coarse_factor * scale
		if int(domain["fine_pixels_per_coarse_cell"]) != fine_per_coarse:
			raise AssertionError(
				f"Domain {domain_id}: inkonsistente Fine/Coarse-Skalierung."
			)

		width = int(domain["coarse_width"]) * fine_per_coarse
		height = int(domain["coarse_height"]) * fine_per_coarse
		if (
			width != int(domain["fine_width"])
			or height != int(domain["fine_height"])
		):
			raise AssertionError(
				f"Domain {domain_id}: inkonsistente Fine-Geometrie."
			)
		x0 = (
			parent_x0
			+ int(domain["coarse_x0"]) * coarse_factor
		) * scale
		y0 = (
			parent_y0
			+ int(domain["coarse_y0"]) * coarse_factor
		) * scale

		domains.append({
			"id": domain_id,
			"zoom": zoom,
			"file": threshold_path(
				threshold_dir,
				{**domain, "id": domain_id},
			).name,
			"global_pixel_x0": x0,
			"global_pixel_y0": y0,
			"global_pixel_x1": x0 + width,
			"global_pixel_y1": y0 + height,
			"width": width,
			"height": height,
			"coarse_x0": int(domain["coarse_x0"]),
			"coarse_y0": int(domain["coarse_y0"]),
			"coarse_width": int(domain["coarse_width"]),
			"coarse_height": int(domain["coarse_height"]),
		})

	levels = [value for value in str(levels_csv).split(",") if value]
	return {
		"schema_version": 1,
		"component_id": int(plan["component_id"]),
		"parent_zoom": parent_zoom,
		"coarse_factor": coarse_factor,
		"tile_size": tile_size,
		"sentinel_class": len(levels),
		"levels": str(levels_csv),
		"domain_count": len(domains),
		"domains": domains,
	}


def validate_adaptive_threshold_output(
	*,
	plan,
	threshold_dir,
	checkpoint_path,
	levels_csv,
	components_report_path=None,
	spans_path=None,
	parent_grid_path=None,
	manifest_output=None,
):
	levels = [value for value in str(levels_csv).split(",") if value]
	sentinel = len(levels)
	if sentinel <= 0 or sentinel > 254:
		raise AssertionError("Ungültige Threshold-Klassen.")

	domains = normalized_domains(plan, sentinel)
	checkpoint = validate_checkpoint(
		domains,
		checkpoint_path,
		levels_csv,
	)
	files = validate_files(domains, threshold_dir, sentinel)
	fixed_point = validate_fixed_point(
		domains,
		threshold_dir,
		sentinel,
	)
	report = {
		"completed": True,
		"domain_count": len(domains),
		"sentinel_class": sentinel,
		"checkpoint_signature": checkpoint["signature"],
		"checkpoint_solver_runs": sum(
			int(domain["runs"])
			for domain in domains.values()
		),
		"checkpoint_zero_run_domains": sum(
			int(domain["runs"]) == 0
			for domain in domains.values()
		),
		"thresholds": files,
		"fixed_point": fixed_point,
	}

	if components_report_path is not None or spans_path is not None:
		if components_report_path is None or spans_path is None:
			raise ValueError(
				"--components-report und --spans müssen gemeinsam "
				"angegeben werden."
			)
		report["component_partition"] = validate_partition(
			plan,
			components_report_path,
			spans_path,
		)

	if parent_grid_path is not None:
		manifest = reconstruction_manifest(
			plan,
			parent_grid_path,
			threshold_dir,
			levels_csv,
		)
		report["reconstruction"] = {
			"domain_count": int(manifest["domain_count"]),
			"parent_zoom": int(manifest["parent_zoom"]),
			"coarse_factor": int(manifest["coarse_factor"]),
			"spatial_mapping_valid": True,
		}
		if manifest_output is not None:
			Path(manifest_output).write_text(
				json.dumps(manifest, indent=2) + "\n",
				encoding="utf-8",
			)

	return report


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Validiert eine finale adaptive sparse Threshold-Ausgabe "
			"gegen Plan und Completed-Checkpoint und erzeugt optional "
			"ein räumliches Rekonstruktionsmanifest."
		)
	)
	parser.add_argument("--adaptive-plan", required=True)
	parser.add_argument("--threshold-dir", required=True)
	parser.add_argument("--checkpoint", required=True)
	parser.add_argument("--levels", required=True)
	parser.add_argument("--components-report")
	parser.add_argument("--spans")
	parser.add_argument("--parent-grid")
	parser.add_argument("--manifest-output")
	parser.add_argument("--report-output")
	args = parser.parse_args()

	plan = json.loads(
		Path(args.adaptive_plan).read_text(encoding="utf-8")
	)
	report = validate_adaptive_threshold_output(
		plan=plan,
		threshold_dir=args.threshold_dir,
		checkpoint_path=args.checkpoint,
		levels_csv=args.levels,
		components_report_path=args.components_report,
		spans_path=args.spans,
		parent_grid_path=args.parent_grid,
		manifest_output=args.manifest_output,
	)
	if args.report_output:
		Path(args.report_output).write_text(
			json.dumps(report, indent=2) + "\n",
			encoding="utf-8",
		)
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
