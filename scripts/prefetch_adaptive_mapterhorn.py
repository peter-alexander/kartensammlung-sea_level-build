#!/usr/bin/env python3

import argparse
import json
from collections import defaultdict
from pathlib import Path

from materialize_adaptive_mapterhorn_domain import (
	adaptive_domain_grid,
	target_tiles_for_grid,
)
from prepare_phase1a_dem import (
	download_task_set,
	resolve_http_fallbacks,
	tile_path,
	tile_url,
)


def collect_tiles(plan, parent_grid, tile_size=512):
	by_zoom = defaultdict(set)
	references = 0

	for domain in plan["domains"]:
		grid = adaptive_domain_grid(
			parent_grid,
			domain,
		)
		tiles = target_tiles_for_grid(
			grid,
			tile_size,
		)
		references += len(tiles)
		for x, y in tiles:
			by_zoom[int(grid["zoom"])].add(
				(int(x), int(y))
			)

	return by_zoom, references


def prefetch(
	plan,
	parent_grid,
	cache_dir,
	*,
	workers=16,
	tile_size=512,
	download=False,
):
	cache_dir = Path(cache_dir)
	by_zoom, references = collect_tiles(
		plan,
		parent_grid,
		tile_size=tile_size,
	)

	report = {
		"domain_count": len(plan["domains"]),
		"tile_references": int(references),
		"unique_tile_count": int(
			sum(len(values) for values in by_zoom.values())
		),
		"unique_tiles_by_zoom": {
			str(zoom): len(values)
			for zoom, values in sorted(by_zoom.items())
		},
		"download": bool(download),
		"requested_missing_tile_count": 0,
		"fallback_target_tile_count": 0,
		"fallback_parent_tile_count": 0,
		"unresolved_tile_count": 0,
	}

	if not download:
		return report

	base_zoom = int(plan["base_zoom"])
	fallback_targets = 0
	fallback_parents = set()
	unresolved = []

	for zoom, coords in sorted(by_zoom.items()):
		tasks = [
			(
				x,
				y,
				tile_url(zoom, x, y),
				tile_path(
					cache_dir,
					zoom,
					x,
					y,
				),
			)
			for x, y in sorted(coords)
		]
		status = download_task_set(
			tasks,
			workers,
			label_zoom=zoom,
		)
		missing = sorted(
			(x, y)
			for x, y in coords
			if status[(x, y)] == "missing"
		)
		report["requested_missing_tile_count"] += len(
			missing
		)

		if not missing:
			continue

		if zoom <= base_zoom:
			unresolved.extend(
				(zoom, x, y)
				for x, y in missing
			)
			continue

		(
			fallbacks,
			unresolved_zoom,
			parent_tiles,
		) = resolve_http_fallbacks(
			missing,
			zoom,
			base_zoom,
			cache_dir,
			workers,
		)
		fallback_targets += len(fallbacks)
		for item in parent_tiles:
			fallback_parents.add((
				int(item["zoom"]),
				int(item["x"]),
				int(item["y"]),
			))
		unresolved.extend(
			(zoom, x, y)
			for x, y in unresolved_zoom
		)

	report["fallback_target_tile_count"] = (
		fallback_targets
	)
	report["fallback_parent_tile_count"] = len(
		fallback_parents
	)
	report["unresolved_tile_count"] = len(unresolved)
	report["unresolved_tiles"] = [
		{
			"zoom": zoom,
			"x": x,
			"y": y,
		}
		for zoom, x, y in unresolved[:100]
	]

	if unresolved:
		raise RuntimeError(
			"Adaptive Prefetch enthält ungelöste Tiles: "
			f"{unresolved[:20]}"
		)

	return report


def main():
	parser = argparse.ArgumentParser(
		description=(
			"Plant oder lädt die eindeutigen Mapterhorn-Tiles "
			"eines adaptiven Domainplans vor."
		)
	)
	parser.add_argument("--adaptive-plan", required=True)
	parser.add_argument("--parent-grid", required=True)
	parser.add_argument("--cache-dir", default="cache")
	parser.add_argument("--workers", type=int, default=16)
	parser.add_argument("--tile-size", type=int, default=512)
	parser.add_argument("--download", action="store_true")
	parser.add_argument("--output", required=True)
	args = parser.parse_args()

	plan = json.loads(
		Path(args.adaptive_plan).read_text(
			encoding="utf-8"
		)
	)
	parent_grid = json.loads(
		Path(args.parent_grid).read_text(
			encoding="utf-8"
		)
	)["grid"]

	report = prefetch(
		plan,
		parent_grid,
		args.cache_dir,
		workers=args.workers,
		tile_size=args.tile_size,
		download=args.download,
	)
	Path(args.output).write_text(
		json.dumps(report, indent=2) + "\n",
		encoding="utf-8",
	)
	print(json.dumps(report, indent=2))


if __name__ == "__main__":
	main()
