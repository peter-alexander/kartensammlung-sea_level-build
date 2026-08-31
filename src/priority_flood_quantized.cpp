#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

struct Options {
	std::string elevationPath;
	std::string seaMaskPath;
	std::string outputPath;
	std::uint32_t width = 0;
	std::uint32_t height = 0;
	std::uint8_t maxLevel = 100;
	double step = 1.0;
	int connectivity = 4;
};

static std::string requireValue(int& index, int argc, char** argv, const std::string& name) {
	if (index + 1 >= argc) {
		throw std::runtime_error("Fehlender Wert für " + name);
	}
	return argv[++index];
}

static Options parseArgs(int argc, char** argv) {
	Options options;

	for (int i = 1; i < argc; ++i) {
		const std::string arg = argv[i];

		if (arg == "--elevation") {
			options.elevationPath = requireValue(i, argc, argv, arg);
		} else if (arg == "--sea-mask") {
			options.seaMaskPath = requireValue(i, argc, argv, arg);
		} else if (arg == "--output") {
			options.outputPath = requireValue(i, argc, argv, arg);
		} else if (arg == "--width") {
			options.width = static_cast<std::uint32_t>(
				std::stoul(requireValue(i, argc, argv, arg))
			);
		} else if (arg == "--height") {
			options.height = static_cast<std::uint32_t>(
				std::stoul(requireValue(i, argc, argv, arg))
			);
		} else if (arg == "--max-level") {
			const unsigned long value = std::stoul(requireValue(i, argc, argv, arg));
			if (value > 253) {
				throw std::runtime_error("--max-level muss <= 253 sein.");
			}
			options.maxLevel = static_cast<std::uint8_t>(value);
		} else if (arg == "--step") {
			options.step = std::stod(requireValue(i, argc, argv, arg));
		} else if (arg == "--connectivity") {
			options.connectivity = std::stoi(requireValue(i, argc, argv, arg));
		} else {
			throw std::runtime_error("Unbekanntes Argument: " + arg);
		}
	}

	if (options.elevationPath.empty() || options.seaMaskPath.empty() || options.outputPath.empty()) {
		throw std::runtime_error("--elevation, --sea-mask und --output sind erforderlich.");
	}
	if (options.width == 0 || options.height == 0) {
		throw std::runtime_error("--width und --height müssen > 0 sein.");
	}
	if (!(options.step > 0.0) || !std::isfinite(options.step)) {
		throw std::runtime_error("--step muss eine positive endliche Zahl sein.");
	}
	if (options.connectivity != 4 && options.connectivity != 8) {
		throw std::runtime_error("--connectivity muss 4 oder 8 sein.");
	}

	return options;
}

template <typename T>
static std::vector<T> readBinary(const std::string& path, std::size_t count) {
	std::ifstream input(path, std::ios::binary);
	if (!input) {
		throw std::runtime_error("Datei konnte nicht geöffnet werden: " + path);
	}

	std::vector<T> data(count);
	input.read(
		reinterpret_cast<char*>(data.data()),
		static_cast<std::streamsize>(count * sizeof(T))
	);

	if (!input || input.gcount() != static_cast<std::streamsize>(count * sizeof(T))) {
		throw std::runtime_error("Unerwartete Dateigröße: " + path);
	}

	char extra = 0;
	if (input.read(&extra, 1)) {
		throw std::runtime_error("Datei enthält mehr Daten als erwartet: " + path);
	}

	return data;
}

template <typename T>
static void writeBinary(const std::string& path, const std::vector<T>& data) {
	std::ofstream output(path, std::ios::binary);
	if (!output) {
		throw std::runtime_error("Ausgabedatei konnte nicht geöffnet werden: " + path);
	}

	output.write(
		reinterpret_cast<const char*>(data.data()),
		static_cast<std::streamsize>(data.size() * sizeof(T))
	);

	if (!output) {
		throw std::runtime_error("Ausgabedatei konnte nicht vollständig geschrieben werden: " + path);
	}
}

static std::uint8_t quantizedElevationLevel(
	float elevation,
	std::uint8_t maxLevel,
	double step
) {
	const std::uint8_t sentinel = static_cast<std::uint8_t>(maxLevel + 1);

	if (!std::isfinite(elevation)) {
		return sentinel;
	}

	if (elevation <= 0.0f) {
		return 0;
	}

	const double quantized = std::ceil(static_cast<double>(elevation) / step - 1e-12);
	if (quantized > static_cast<double>(maxLevel)) {
		return sentinel;
	}

	return static_cast<std::uint8_t>(std::max(0.0, quantized));
}

static std::vector<std::uint8_t> computeThreshold(
	const std::vector<float>& elevation,
	const std::vector<std::uint8_t>& seaMask,
	std::uint32_t width,
	std::uint32_t height,
	std::uint8_t maxLevel,
	double step,
	int connectivity
) {
	const std::size_t cellCount = static_cast<std::size_t>(width) * height;
	const std::uint8_t sentinel = static_cast<std::uint8_t>(maxLevel + 1);
	const std::uint8_t unvisited = 255;

	std::vector<std::uint8_t> threshold(cellCount, unvisited);
	std::vector<std::vector<std::uint32_t>> buckets(
		static_cast<std::size_t>(maxLevel) + 1
	);

	std::size_t seedCount = 0;
	for (std::size_t index = 0; index < cellCount; ++index) {
		if (seaMask[index] == 0) {
			continue;
		}

		if (index > std::numeric_limits<std::uint32_t>::max()) {
			throw std::runtime_error("Raster ist für 32-Bit-Zellindizes zu groß.");
		}

		threshold[index] = 0;
		buckets[0].push_back(static_cast<std::uint32_t>(index));
		++seedCount;
	}

	if (seedCount == 0) {
		throw std::runtime_error("Sea-Maske enthält keine Seed-Zelle.");
	}

	std::size_t processed = 0;

	auto visitNeighbor = [&](std::uint32_t neighborIndex, std::uint8_t currentLevel) {
		if (threshold[neighborIndex] != unvisited) {
			return;
		}

		const std::uint8_t cellLevel = quantizedElevationLevel(
			elevation[neighborIndex],
			maxLevel,
			step
		);

		if (cellLevel == sentinel) {
			threshold[neighborIndex] = sentinel;
			return;
		}

		const std::uint8_t nextLevel = std::max(currentLevel, cellLevel);
		threshold[neighborIndex] = nextLevel;
		buckets[nextLevel].push_back(neighborIndex);
	};

	for (std::uint16_t levelValue = 0; levelValue <= maxLevel; ++levelValue) {
		const std::uint8_t level = static_cast<std::uint8_t>(levelValue);
		auto& bucket = buckets[level];

		for (std::size_t cursor = 0; cursor < bucket.size(); ++cursor) {
			const std::uint32_t index = bucket[cursor];
			const std::uint32_t row = index / width;
			const std::uint32_t col = index - row * width;

			if (row > 0) {
				visitNeighbor(index - width, level);
			}
			if (col > 0) {
				visitNeighbor(index - 1, level);
			}
			if (col + 1 < width) {
				visitNeighbor(index + 1, level);
			}
			if (row + 1 < height) {
				visitNeighbor(index + width, level);
			}

			if (connectivity == 8) {
				if (row > 0 && col > 0) {
					visitNeighbor(index - width - 1, level);
				}
				if (row > 0 && col + 1 < width) {
					visitNeighbor(index - width + 1, level);
				}
				if (row + 1 < height && col > 0) {
					visitNeighbor(index + width - 1, level);
				}
				if (row + 1 < height && col + 1 < width) {
					visitNeighbor(index + width + 1, level);
				}
			}

			++processed;
		}

		std::cerr
			<< "level=" << levelValue
			<< " cells=" << bucket.size()
			<< " processed=" << processed
			<< "\n";

		std::vector<std::uint32_t>().swap(bucket);
	}

	std::size_t disconnected = 0;
	for (std::uint8_t& value : threshold) {
		if (value == unvisited) {
			value = sentinel;
			++disconnected;
		}
	}

	std::cerr
		<< "seeds=" << seedCount
		<< " processed=" << processed
		<< " sentinel_or_disconnected="
		<< std::count(threshold.begin(), threshold.end(), sentinel)
		<< " disconnected=" << disconnected
		<< "\n";

	return threshold;
}

int main(int argc, char** argv) {
	try {
		const Options options = parseArgs(argc, argv);
		const std::size_t cellCount =
			static_cast<std::size_t>(options.width) * options.height;

		if (cellCount > std::numeric_limits<std::uint32_t>::max()) {
			throw std::runtime_error(
				"Raster hat mehr als 2^32-1 Zellen; Pilotkern unterstützt das noch nicht."
			);
		}

		const std::vector<float> elevation = readBinary<float>(
			options.elevationPath,
			cellCount
		);
		const std::vector<std::uint8_t> seaMask = readBinary<std::uint8_t>(
			options.seaMaskPath,
			cellCount
		);

		const std::vector<std::uint8_t> threshold = computeThreshold(
			elevation,
			seaMask,
			options.width,
			options.height,
			options.maxLevel,
			options.step,
			options.connectivity
		);

		writeBinary(options.outputPath, threshold);
		return 0;
	} catch (const std::exception& error) {
		std::cerr << "Fehler: " << error.what() << "\n";
		return 1;
	}
}
