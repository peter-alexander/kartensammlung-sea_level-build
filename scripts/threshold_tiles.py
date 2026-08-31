#!/usr/bin/env python3

import argparse
from pathlib import Path

try:
	import numpy as np
	import rasterio
	from PIL import Image
except ImportError as error:
	raise SystemExit(
		"Benötigt: numpy, pillow, rasterio (pip install numpy pillow rasterio)"
	) from error


TERRARIUM_OFFSET = 32768.0
TERRARIUM_SCALE = 256.0
TERRARIUM_MAX_RAW = 256 * 256 * 256 - 1


def encode_terrarium(values):
	array = np.asarray(values, dtype=np.float64)

	if not np.all(np.isfinite(array)):
		raise ValueError("Threshold-Raster enthält nicht-endliche Werte.")

	raw = np.rint((array + TERRARIUM_OFFSET) * TERRARIUM_SCALE).astype(np.int64)
	raw = np.clip(raw, 0, TERRARIUM_MAX_RAW)

	red = ((raw >> 16) & 255).astype(np.uint8)
	green = ((raw >> 8) & 255).astype(np.uint8)
	blue = (raw & 255).astype(np.uint8)

	return np.stack((red, green, blue), axis=-1)


def decode_terrarium(rgb):
	array = np.asarray(rgb, dtype=np.float64)

	return (
		array[:, :, 0] * 256.0
		+ array[:, :, 1]
		+ array[:, :, 2] / 256.0
		- TERRARIUM_OFFSET
	)


def write_tiles(
	input_path,
	output_dir,
	*,
	zoom,
	x_min,
	y_min,
	tile_size=512,
):
	with rasterio.open(input_path) as dataset:
		threshold = dataset.read(1).astype(np.float64)

	rows, cols = threshold.shape

	if rows % tile_size != 0 or cols % tile_size != 0:
		raise ValueError(
			f"Rastergröße {cols}x{rows} ist kein Vielfaches von {tile_size}."
		)

	rgb = encode_terrarium(threshold)
	decoded = decode_terrarium(rgb)
	max_error = float(np.max(np.abs(decoded - threshold)))

	if max_error > (1.0 / TERRARIUM_SCALE):
		raise RuntimeError(
			f"Terrarium-Roundtrip ist zu ungenau: {max_error:.8f} m."
		)

	tile_rows = rows // tile_size
	tile_cols = cols // tile_size
	output_dir = Path(output_dir)
	written = []

	for tile_row in range(tile_rows):
		for tile_col in range(tile_cols):
			x = x_min + tile_col
			y = y_min + tile_row
			tile = rgb[
				tile_row * tile_size:(tile_row + 1) * tile_size,
				tile_col * tile_size:(tile_col + 1) * tile_size,
			]

			path = output_dir / str(zoom) / str(x) / f"{y}.png"
			path.parent.mkdir(parents=True, exist_ok=True)
			Image.fromarray(tile, "RGB").save(path, optimize=True)
			written.append(path)

	return {
		"rows": rows,
		"cols": cols,
		"tile_rows": tile_rows,
		"tile_cols": tile_cols,
		"tile_count": len(written),
		"min_threshold_m": float(np.min(threshold)),
		"max_threshold_m": float(np.max(threshold)),
		"max_roundtrip_error_m": max_error,
		"files": written,
	}


def main():
	parser = argparse.ArgumentParser(
		description="Exportiert ein Inundation-Threshold-GeoTIFF als Terrarium-PNG-Kacheln."
	)
	parser.add_argument("--input", required=True)
	parser.add_argument("--output-dir", required=True)
	parser.add_argument("--zoom", type=int, required=True)
	parser.add_argument("--x-min", type=int, required=True)
	parser.add_argument("--y-min", type=int, required=True)
	parser.add_argument("--tile-size", type=int, default=512)
	args = parser.parse_args()

	result = write_tiles(
		args.input,
		args.output_dir,
		zoom=args.zoom,
		x_min=args.x_min,
		y_min=args.y_min,
		tile_size=args.tile_size,
	)

	print(
		f"{result['tile_count']} Tiles geschrieben; "
		f"Threshold {result['min_threshold_m']:.5f} bis {result['max_threshold_m']:.5f} m; "
		f"max. Roundtrip-Fehler {result['max_roundtrip_error_m']:.8f} m."
	)


if __name__ == "__main__":
	main()
