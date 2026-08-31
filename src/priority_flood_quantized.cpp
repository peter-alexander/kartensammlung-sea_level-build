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
	std::string boundaryThresholdPath;
	std::string outputPath;
	std::uint32_t width = 0;
	std::uint32_t height = 0;
	std::vector<double> levels;
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
		} else if (arg == "--boundary-threshold") {
			options.boundaryThresholdPath = requireValue(i, argc, argv, arg);
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
		} else if (arg == "--levels") {
			const std::string value = requireValue(i, argc, argv, arg);
			std::size_t start = 0;

			while (start <= value.size()) {
				const std::size_t end = value.find(',', start);
				const std::string token = value.substr(
					start,
					end == std::string::npos ? std::string::npos : end - start
				);
				if (token.empty()) {
					throw std::runtime_error("--levels enthält einen leeren Wert.");
				}
				options.levels.push_back(std::stod(token));
				if (end == std::string::npos) break;
				start = end + 1;
			}
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
	if (options.levels.empty()) {
		throw std::runtime_error("--levels ist erforderlich.");
	}
	if (options.levels.size() > 254) {
		throw std::runtime_error("--levels darf höchstens 254 Klassen enthalten.");
	}
	if (std::abs(options.levels.front()) > 1e-12) {
		throw std::runtime_error("Die erste Threshold-Klasse muss 0 m sein.");
	}
	for (std::size_t index = 0; index < options.levels.size(); ++index) {
		if (!std::isfinite(options.levels[index]) || options.levels[index] < 0.0) {
			throw std::runtime_error("--levels enthält einen ungültigen Wert.");
		}
		if (index > 0 && !(options.levels[index] > options.levels[index - 1])) {
			throw std::runtime_error("--levels muss streng monoton steigen.");
		}
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
	const std::vector<double>& levels
) {
	const std::uint8_t sentinel = static_cast<std::uint8_t>(levels.size());

	if (!std::isfinite(elevation)) return sentinel;
	if (elevation <= 0.0f) return 0;

	const double value = static_cast<double>(elevation) - 1e-12;
	const auto found = std::lower_bound(levels.begin(), levels.end(), value);
	if (found == levels.end()) return sentinel;

	return static_cast<std::uint8_t>(std::distance(levels.begin(), found));
}

static std::vector<std::uint8_t> computeThreshold(
	const std::vector<float>& elevation,
	const std::vector<std::uint8_t>& seaMask,
	const std::vector<std::uint8_t>* boundaryThreshold,
	std::uint32_t width,
	std::uint32_t height,
	const std::vector<double>& levels,
	int connectivity
) {
	const std::size_t cellCount = static_cast<std::size_t>(width) * height;
	const std::uint8_t sentinel = static_cast<std::uint8_t>(levels.size());
	const std::uint8_t unvisited = 255;

	std::vector<std::uint8_t> threshold(cellCount, unvisited);
	std::vector<std::vector<std::uint32_t>> buckets(levels.size());

	std::size_t seaSeedCount = 0;
	std::size_t boundarySeedCount = 0;

	auto enqueueSeed = [&](std::uint32_t index, std::uint8_t level) {
		if (level >= levels.size()) {
			return false;
		}
		if (threshold[index] <= level) {
			return false;
		}

		threshold[index] = level;
		buckets[level].push_back(index);
		return true;
	};

	for (std::size_t index = 0; index < cellCount; ++index) {
		if (seaMask[index] == 0) {
			continue;
		}

		if (index > std::numeric_limits<std::uint32_t>::max()) {
			throw std::runtime_error("Raster ist für 32-Bit-Zellindizes zu groß.");
		}

		if (enqueueSeed(static_cast<std::uint32_t>(index), 0)) {
			++seaSeedCount;
		}
	}

	if (boundaryThreshold) {
		if (boundaryThreshold->size() != cellCount) {
			throw std::runtime_error("Boundary-Threshold hat eine falsche Rastergröße.");
		}

		for (std::size_t index = 0; index < cellCount; ++index) {
			const std::uint8_t coarseLevel = (*boundaryThreshold)[index];

			if (coarseLevel == unvisited || coarseLevel == sentinel) {
				continue;
			}
			if (coarseLevel > sentinel) {
				throw std::runtime_error(
					"Boundary-Threshold enthält einen ungültigen Wert."
				);
			}

			const std::uint32_t row = static_cast<std::uint32_t>(index / width);
			const std::uint32_t col = static_cast<std::uint32_t>(index - row * width);

			if (
				row != 0
				&& col != 0
				&& row + 1 != height
				&& col + 1 != width
			) {
				throw std::runtime_error(
					"Boundary-Threshold enthält einen Seed außerhalb des Rasterrands."
				);
			}

			const std::uint8_t cellLevel = quantizedElevationLevel(
				elevation[index],
				levels
			);

			if (cellLevel == sentinel) {
				continue;
			}

			const std::uint8_t seedLevel = std::max(coarseLevel, cellLevel);
			if (enqueueSeed(static_cast<std::uint32_t>(index), seedLevel)) {
				++boundarySeedCount;
			}
		}
	}

	if (seaSeedCount == 0 && boundarySeedCount == 0) {
		throw std::runtime_error(
			"Weder Sea-Maske noch Boundary-Threshold enthalten einen nutzbaren Seed."
		);
	}

	std::size_t processed = 0;
	std::size_t staleEntries = 0;

	auto visitNeighbor = [&](std::uint32_t neighborIndex, std::uint8_t currentLevel) {
		const std::uint8_t cellLevel = quantizedElevationLevel(
			elevation[neighborIndex],
			levels
		);

		if (cellLevel == sentinel) {
			if (threshold[neighborIndex] == unvisited) {
				threshold[neighborIndex] = sentinel;
			}
			return;
		}

		const std::uint8_t nextLevel = std::max(currentLevel, cellLevel);
		if (threshold[neighborIndex] <= nextLevel) {
			return;
		}

		threshold[neighborIndex] = nextLevel;
		buckets[nextLevel].push_back(neighborIndex);
	};

	for (std::uint16_t levelValue = 0; levelValue < levels.size(); ++levelValue) {
		const std::uint8_t level = static_cast<std::uint8_t>(levelValue);
		auto& bucket = buckets[level];

		for (std::size_t cursor = 0; cursor < bucket.size(); ++cursor) {
			const std::uint32_t index = bucket[cursor];

			if (threshold[index] != level) {
				++staleEntries;
				continue;
			}

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
			<< "level_index=" << levelValue
			<< " level_m=" << levels[levelValue]
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
		<< "sea_seeds=" << seaSeedCount
		<< " boundary_seeds=" << boundarySeedCount
		<< " processed=" << processed
		<< " stale_entries=" << staleEntries
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

		std::vector<std::uint8_t> boundaryThreshold;
		const std::vector<std::uint8_t>* boundaryThresholdPtr = nullptr;
		if (!options.boundaryThresholdPath.empty()) {
			boundaryThreshold = readBinary<std::uint8_t>(
				options.boundaryThresholdPath,
				cellCount
			);
			boundaryThresholdPtr = &boundaryThreshold;
		}

		const std::vector<std::uint8_t> threshold = computeThreshold(
			elevation,
			seaMask,
			boundaryThresholdPtr,
			options.width,
			options.height,
			options.levels,
			options.connectivity
		);

		writeBinary(options.outputPath, threshold);
		return 0;
	} catch (const std::exception& error) {
		std::cerr << "Fehler: " << error.what() << "\n";
		return 1;
	}
}
