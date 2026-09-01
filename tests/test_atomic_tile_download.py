#!/usr/bin/env python3

import http.client
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_phase1a_dem import download_tile


class Response:
	def __init__(self, reader):
		self.reader = reader

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc, tb):
		return False

	def read(self):
		return self.reader()


def main():
	original = urllib.request.urlopen

	try:
		with tempfile.TemporaryDirectory() as tmp:
			tmp = Path(tmp)
			path = tmp / "tile.webp"
			calls = []

			def flaky(_request, timeout):
				calls.append(timeout)
				if len(calls) == 1:
					return Response(
						lambda: (
							_ for _ in ()
						).throw(
							http.client.IncompleteRead(
								b"partial",
								20,
							)
						)
					)
				return Response(lambda: b"complete")

			urllib.request.urlopen = flaky

			status = download_tile(
				"https://example.test/tile.webp",
				path,
				max_attempts=2,
				retry_delay_seconds=0,
			)
			if status != "downloaded":
				raise AssertionError(status)
			if path.read_bytes() != b"complete":
				raise AssertionError(
					"Partieller Download wurde übernommen."
				)
			if len(calls) != 2:
				raise AssertionError(calls)
			if list(tmp.glob("*.part-*")):
				raise AssertionError(
					"Temporäre Download-Datei blieb liegen."
				)

			status = download_tile(
				"https://example.test/tile.webp",
				path,
			)
			if status != "cached":
				raise AssertionError(status)
			if len(calls) != 2:
				raise AssertionError(
					"Cache-Hit darf keinen Request auslösen."
				)

			missing = tmp / "missing.webp"

			def not_found(_request, timeout):
				raise urllib.error.HTTPError(
					"https://example.test/missing.webp",
					404,
					"not found",
					None,
					None,
				)

			urllib.request.urlopen = not_found
			status = download_tile(
				"https://example.test/missing.webp",
				missing,
				retry_delay_seconds=0,
			)
			if status != "missing":
				raise AssertionError(status)
			if missing.exists():
				raise AssertionError(
					"404 darf keine Cache-Datei erzeugen."
				)
	finally:
		urllib.request.urlopen = original

	print("ok")


if __name__ == "__main__":
	main()
