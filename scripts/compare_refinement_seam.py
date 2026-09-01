#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import numpy as np

from build_composite_threshold import (
	add_metrics,
	add_slider_disagreement,
	collect_edge_outliers,
	core_mask_chunk,
	finish_metrics,
	finish_slider_disagreement,
	load_core_feature,
	metric_state,
	parent_clip_edge_mask,
	slider_disagreement_state,
)


def load_grid(path):
	return json.loads(Path(path).read_text(encoding="utf-8"))["grid"]


def sample_base_chunk(
	base,
	base_grid,
	fine_grid,
	row_start,
	row_end,
):
	cols = np.arange(fine_grid["width"], dtype=np.float64)
	rows = np.arange(row_start, row_end, dtype=np.float64)

	x = (
		float(fine_grid["left"])
		+ (cols + 0.5) * float(fine_grid["resolution"])
	)
	y = (
		float(fine_grid["top"])
		- (rows + 0.5) * float(fine_grid["resolution"])
	)

	base_cols = np.floor(
		(x - float(base_grid["left"]))
		/ float(base_grid["resolution"])
	).astype(np.int64)
	base_rows = np.floor(
		(float(base_grid["top"]) - y)
		/ float(base_grid["resolution"])
	).astype(np.int64)

	if (
		np.any(base_cols < 0)
		or np.any(base_cols >= int(base_grid["width"]))
		or np.any(base_rows < 0)
		or np.any(base_rows >= int(base_grid["height"]))
	):
		raise ValueError(
			"Fine-Workarea liegt nicht vollständig im Base-Raster."
		)

	return np.asarray(
		base[
			base_rows[:, None],
			base_cols[None, :],
		]
	)


def compare_refinement_seam(
	base_grid_path,
	base_threshold_path,
	fine_grid_path,
	fine_threshold_path,
	core_geojson_path,
	*,
	chunk_rows=128,
):
	base_grid = load_grid(base_grid_path)
	fine_grid = load_grid(fine_grid_path)

	base = np.memmap(
		base_threshold_path,
		dtype=np.uint8,
		mode="r",
		shape=(base_grid["height"], base_grid["width"]),
	)
	fine = np.memmap(
		fine_threshold_path,
		dtype=np.uint8,
		mode="r",
		shape=(fine_grid["height"], fine_grid["width"]),
	)

	core, core_properties = load_core_feature(core_geojson_path)

	edge_metrics = metric_state()
	source_seam_metrics = metric_state()
	parent_clip_metrics = metric_state()
	edge_slider = slider_disagreement_state()
	source_seam_slider = slider_disagreement_state()
	parent_clip_slider = slider_disagreement_state()
	edge_outliers = []
	source_seam_outliers = []
	parent_clip_outliers = []

	for fine_row in range(0, fine_grid["height"], chunk_rows):
		fine_row_end = min(
			fine_grid["height"],
			fine_row + chunk_rows,
		)
		mask = core_mask_chunk(
			core,
			fine_grid,
			fine_row,
			fine_row_end,
		)
		if not np.any(mask):
			continue

		extended_start = max(0, fine_row - 1)
		extended_end = min(
			fine_grid["height"],
			fine_row_end + 1,
		)
		extended = core_mask_chunk(
			core,
			fine_grid,
			extended_start,
			extended_end,
		)

		local_start = fine_row - extended_start
		local_end = local_start + (fine_row_end - fine_row)
		center = extended[local_start:local_end, :]

		up = np.zeros_like(center)
		down = np.zeros_like(center)
		left = np.zeros_like(center)
		right = np.zeros_like(center)

		if fine_row > 0:
			up[:] = extended[local_start - 1:local_end - 1, :]
		if fine_row_end < fine_grid["height"]:
			down[:] = extended[local_start + 1:local_end + 1, :]

		left[:, 1:] = center[:, :-1]
		right[:, :-1] = center[:, 1:]

		edge = center & ~(up & down & left & right)
		if not np.any(edge):
			continue

		parent_clip_edge = parent_clip_edge_mask(
			edge,
			fine_grid,
			fine_row,
			core_properties,
		)
		source_seam_edge = edge & ~parent_clip_edge

		fine_values = np.asarray(
			fine[fine_row:fine_row_end, :]
		)
		base_values = sample_base_chunk(
			base,
			base_grid,
			fine_grid,
			fine_row,
			fine_row_end,
		)

		for metrics, slider, seam_mask in (
			(edge_metrics, edge_slider, edge),
			(
				source_seam_metrics,
				source_seam_slider,
				source_seam_edge,
			),
			(
				parent_clip_metrics,
				parent_clip_slider,
				parent_clip_edge,
			),
		):
			add_metrics(
				metrics,
				fine_values,
				base_values,
				seam_mask,
			)
			add_slider_disagreement(
				slider,
				fine_values,
				base_values,
				seam_mask,
			)

		collect_edge_outliers(
			edge_outliers,
			fine_values,
			base_values,
			edge,
			fine_grid,
			fine_row,
			edge_kind="all_core_edge",
		)
		collect_edge_outliers(
			source_seam_outliers,
			fine_values,
			base_values,
			source_seam_edge,
			fine_grid,
			fine_row,
			edge_kind="source_coverage_seam",
		)
		collect_edge_outliers(
			parent_clip_outliers,
			fine_values,
			base_values,
			parent_clip_edge,
			fine_grid,
			fine_row,
			edge_kind="parent_clip_boundary",
		)

	return {
		"base_zoom": int(base_grid["zoom"]),
		"fine_zoom": int(fine_grid["zoom"]),
		"core_edge_vs_upsampled_base": finish_metrics(
			edge_metrics
		),
		"refinement_seam_vs_upsampled_base": finish_metrics(
			source_seam_metrics
		),
		"parent_clip_boundary_vs_upsampled_base": finish_metrics(
			parent_clip_metrics
		),
		"core_edge_slider_disagreement_vs_upsampled_base": (
			finish_slider_disagreement(edge_slider)
		),
		"refinement_seam_slider_disagreement_vs_upsampled_base": (
			finish_slider_disagreement(source_seam_slider)
		),
		"parent_clip_slider_disagreement_vs_upsampled_base": (
			finish_slider_disagreement(parent_clip_slider)
		),
		"core_edge_top_outliers": edge_outliers,
		"refinement_seam_top_outliers": source_seam_outliers,
		"parent_clip_boundary_top_outliers": parent_clip_outliers,
	}


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--base-grid", required=True)
	parser.add_argument("--base-threshold", required=True)
	parser.add_argument("--fine-grid", required=True)
	parser.add_argument("--fine-threshold", required=True)
	parser.add_argument("--core-geojson", required=True)
	parser.add_argument("--output", required=True)
	parser.add_argument("--chunk-rows", type=int, default=128)
	args = parser.parse_args()

	if args.chunk_rows <= 0:
		parser.error("--chunk-rows muss > 0 sein.")

	report = compare_refinement_seam(
		args.base_grid,
		args.base_threshold,
		args.fine_grid,
		args.fine_threshold,
		args.core_geojson,
		chunk_rows=args.chunk_rows,
	)

	Path(args.output).parent.mkdir(parents=True, exist_ok=True)
	Path(args.output).write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
