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
	std::string landMaskPath;
	std::string outputPath;
	std::uint32_t width = 0;
	std::uint32_t height = 0;
	std::vector<double> levels;
};

class PackedBits {
public:
	explicit PackedBits(std::size_t bitCount)
		: data_((bitCount + 7) / 8, 0) {}

	bool get(std::size_t index) const {
		return (
			data_[index >> 3]
			& static_cast<std::uint8_t>(1u << (index & 7u))
		) != 0;
	}

	void set(std::size_t index) {
		data_[index >> 3] |= static_cast<std::uint8_t>(
			1u << (index & 7u)
		);
	}

	std::vector<std::uint8_t>& data() {
		return data_;
	}

	std::size_t bytes() const {
		return data_.size();
	}

private:
	std::vector<std::uint8_t> data_;
};

static std::string requireValue(
	int& index,
	int argc,
	char** argv,
	const std::string& name
) {
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
			options.elevationPath = requireValue(
				i,
				argc,
				argv,
				arg
			);
		} else if (arg == "--sea-mask") {
			options.seaMaskPath = requireValue(
				i,
				argc,
				argv,
				arg
			);
		} else if (arg == "--land-mask") {
			options.landMaskPath = requireValue(
				i,
				argc,
				argv,
				arg
			);
		} else if (arg == "--output") {
			options.outputPath = requireValue(
				i,
				argc,
				argv,
				arg
			);
		} else if (arg == "--width") {
			options.width = static_cast<std::uint32_t>(
				std::stoul(
					requireValue(i, argc, argv, arg)
				)
			);
		} else if (arg == "--height") {
			options.height = static_cast<std::uint32_t>(
				std::stoul(
					requireValue(i, argc, argv, arg)
				)
			);
		} else if (arg == "--levels") {
			const std::string value = requireValue(
				i,
				argc,
				argv,
				arg
			);
			std::size_t start = 0;

			while (start <= value.size()) {
				const std::size_t end = value.find(
					',',
					start
				);
				const std::string token = value.substr(
					start,
					end == std::string::npos
						? std::string::npos
						: end - start
				);
				if (token.empty()) {
					throw std::runtime_error(
						"--levels enthält einen leeren Wert."
					);
				}
				options.levels.push_back(
					std::stod(token)
				);
				if (end == std::string::npos) {
					break;
				}
				start = end + 1;
			}
		} else {
			throw std::runtime_error(
				"Unbekanntes Argument: " + arg
			);
		}
	}

	if (
		options.elevationPath.empty()
		|| options.seaMaskPath.empty()
		|| options.landMaskPath.empty()
		|| options.outputPath.empty()
	) {
		throw std::runtime_error(
			"--elevation, --sea-mask, --land-mask und "
			"--output sind erforderlich."
		);
	}
	if (options.width == 0 || options.height == 0) {
		throw std::runtime_error(
			"--width und --height müssen > 0 sein."
		);
	}
	if (options.levels.empty()) {
		throw std::runtime_error("--levels ist erforderlich.");
	}
	if (options.levels.size() > 254) {
		throw std::runtime_error(
			"--levels darf höchstens 254 Klassen enthalten."
		);
	}
	if (std::abs(options.levels.front()) > 1e-12) {
		throw std::runtime_error(
			"Die erste Threshold-Klasse muss 0 m sein."
		);
	}

	for (
		std::size_t index = 0;
		index < options.levels.size();
		++index
	) {
		if (
			!std::isfinite(options.levels[index])
			|| options.levels[index] < 0.0
		) {
			throw std::runtime_error(
				"--levels enthält einen ungültigen Wert."
			);
		}
		if (
			index > 0
			&& !(
				options.levels[index]
				> options.levels[index - 1]
			)
		) {
			throw std::runtime_error(
				"--levels muss streng monoton steigen."
			);
		}
	}

	return options;
}

static std::uint64_t fileSize(const std::string& path) {
	std::ifstream input(
		path,
		std::ios::binary | std::ios::ate
	);
	if (!input) {
		throw std::runtime_error(
			"Datei konnte nicht geöffnet werden: " + path
		);
	}
	return static_cast<std::uint64_t>(input.tellg());
}

template <typename T>
static std::vector<T> readBinary(
	const std::string& path,
	std::size_t count
) {
	if (
		fileSize(path)
		!= static_cast<std::uint64_t>(
			count * sizeof(T)
		)
	) {
		throw std::runtime_error(
			"Unerwartete Dateigröße: " + path
		);
	}

	std::vector<T> result(count);
	std::ifstream input(path, std::ios::binary);
	input.read(
		reinterpret_cast<char*>(result.data()),
		static_cast<std::streamsize>(
			count * sizeof(T)
		)
	);
	if (!input) {
		throw std::runtime_error(
			"Datei konnte nicht vollständig gelesen werden: "
			+ path
		);
	}

	return result;
}

static PackedBits readPacked(
	const std::string& path,
	std::size_t cellCount
) {
	PackedBits bits(cellCount);
	if (fileSize(path) != bits.bytes()) {
		throw std::runtime_error(
			"Unerwartete Packed-Mask-Dateigröße: " + path
		);
	}

	std::ifstream input(path, std::ios::binary);
	input.read(
		reinterpret_cast<char*>(bits.data().data()),
		static_cast<std::streamsize>(bits.bytes())
	);
	if (!input) {
		throw std::runtime_error(
			"Packed-Maske konnte nicht vollständig gelesen werden."
		);
	}

	return bits;
}

static PackedBits packSeaMask(
	const std::string& path,
	std::size_t cellCount
) {
	if (fileSize(path) != cellCount) {
		throw std::runtime_error(
			"Unerwartete Sea-Mask-Dateigröße."
		);
	}

	PackedBits seaBits(cellCount);
	constexpr std::size_t chunkCells = 1u << 20;
	std::vector<std::uint8_t> chunk(chunkCells);
	std::ifstream input(path, std::ios::binary);

	for (
		std::size_t offset = 0;
		offset < cellCount;
		offset += chunkCells
	) {
		const std::size_t count = std::min(
			chunkCells,
			cellCount - offset
		);
		input.read(
			reinterpret_cast<char*>(chunk.data()),
			static_cast<std::streamsize>(count)
		);
		if (!input) {
			throw std::runtime_error(
				"Sea-Maske konnte nicht vollständig gelesen werden."
			);
		}

		for (std::size_t local = 0; local < count; ++local) {
			if (chunk[local] != 0) {
				seaBits.set(offset + local);
			}
		}
	}

	return seaBits;
}

static std::uint8_t quantizedElevationLevel(
	float elevation,
	const std::vector<double>& levels
) {
	const std::uint8_t sentinel =
		static_cast<std::uint8_t>(levels.size());

	if (!std::isfinite(elevation)) {
		return sentinel;
	}
	if (elevation <= 0.0f) {
		return 0;
	}

	const double value =
		static_cast<double>(elevation) - 1e-12;
	const auto found = std::lower_bound(
		levels.begin(),
		levels.end(),
		value
	);
	if (found == levels.end()) {
		return sentinel;
	}

	return static_cast<std::uint8_t>(
		std::distance(levels.begin(), found)
	);
}

static bool touchesSea(
	const PackedBits& seaBits,
	std::size_t index,
	std::uint32_t width,
	std::uint32_t height
) {
	const std::uint32_t row =
		static_cast<std::uint32_t>(index / width);
	const std::uint32_t col =
		static_cast<std::uint32_t>(
			index
			- static_cast<std::size_t>(row) * width
		);

	if (col > 0 && seaBits.get(index - 1)) {
		return true;
	}
	if (col + 1 < width && seaBits.get(index + 1)) {
		return true;
	}
	if (row > 0 && seaBits.get(index - width)) {
		return true;
	}
	if (row + 1 < height && seaBits.get(index + width)) {
		return true;
	}

	return false;
}

static std::vector<std::uint8_t> solveLandMask(
	const std::vector<float>& elevation,
	const PackedBits& landMask,
	const PackedBits& seaBits,
	std::uint32_t width,
	std::uint32_t height,
	const std::vector<double>& levels
) {
	const std::size_t cellCount =
		static_cast<std::size_t>(width) * height;
	const std::uint8_t sentinel =
		static_cast<std::uint8_t>(levels.size());
	const std::uint8_t unvisited = 255;

	std::vector<std::uint8_t> elevationLevel(
		cellCount,
		sentinel
	);
	std::vector<std::uint8_t> threshold(
		cellCount,
		sentinel
	);
	std::vector<std::vector<std::uint32_t>> buckets(
		levels.size()
	);

	std::size_t landCells = 0;
	std::size_t coastalSeeds = 0;
	std::size_t maskedAboveMax = 0;

	for (std::size_t index = 0; index < cellCount; ++index) {
		if (!landMask.get(index)) {
			continue;
		}

		++landCells;
		const std::uint8_t cellLevel =
			quantizedElevationLevel(
				elevation[index],
				levels
			);
		elevationLevel[index] = cellLevel;

		if (cellLevel == sentinel) {
			++maskedAboveMax;
			continue;
		}

		threshold[index] = unvisited;

		if (!touchesSea(
			seaBits,
			index,
			width,
			height
		)) {
			continue;
		}

		threshold[index] = cellLevel;
		buckets[cellLevel].push_back(
			static_cast<std::uint32_t>(index)
		);
		++coastalSeeds;
	}

	if (coastalSeeds == 0 && landCells != 0) {
		throw std::runtime_error(
			"Landmaske enthält keine nutzbare Küsten-Seedzelle."
		);
	}

	std::size_t processed = 0;

	auto visitNeighbor = [&](
		std::uint32_t neighbor,
		std::uint8_t currentLevel
	) {
		if (!landMask.get(neighbor)) {
			return;
		}

		const std::uint8_t cellLevel =
			elevationLevel[neighbor];
		if (cellLevel == sentinel) {
			return;
		}

		const std::uint8_t nextLevel = std::max(
			currentLevel,
			cellLevel
		);
		if (threshold[neighbor] <= nextLevel) {
			return;
		}

		threshold[neighbor] = nextLevel;
		buckets[nextLevel].push_back(neighbor);
	};

	for (
		std::uint16_t levelValue = 0;
		levelValue < levels.size();
		++levelValue
	) {
		const std::uint8_t level =
			static_cast<std::uint8_t>(levelValue);
		auto& bucket = buckets[level];

		for (
			std::size_t cursor = 0;
			cursor < bucket.size();
			++cursor
		) {
			const std::uint32_t index = bucket[cursor];

			if (threshold[index] != level) {
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

			++processed;
		}

		std::vector<std::uint32_t>().swap(bucket);
	}

	std::size_t disconnected = 0;
	for (std::size_t index = 0; index < cellCount; ++index) {
		if (
			landMask.get(index)
			&& threshold[index] == unvisited
		) {
			threshold[index] = sentinel;
			++disconnected;
		}
	}

	std::cerr
		<< "land_cells=" << landCells
		<< " coastal_seeds=" << coastalSeeds
		<< " processed=" << processed
		<< " masked_above_max=" << maskedAboveMax
		<< " disconnected=" << disconnected
		<< "\n";

	return threshold;
}

static void writeBinary(
	const std::string& path,
	const std::vector<std::uint8_t>& data
) {
	std::ofstream output(path, std::ios::binary);
	if (!output) {
		throw std::runtime_error(
			"Ausgabedatei konnte nicht geöffnet werden."
		);
	}

	output.write(
		reinterpret_cast<const char*>(data.data()),
		static_cast<std::streamsize>(data.size())
	);
	if (!output) {
		throw std::runtime_error(
			"Ausgabedatei konnte nicht vollständig geschrieben werden."
		);
	}
}

int main(int argc, char** argv) {
	try {
		const Options options = parseArgs(argc, argv);
		const std::size_t cellCount =
			static_cast<std::size_t>(options.width)
			* options.height;

		if (
			cellCount
			> std::numeric_limits<std::uint32_t>::max()
		) {
			throw std::runtime_error(
				"Raster hat mehr als 2^32-1 Zellen."
			);
		}

		std::vector<float> elevation = readBinary<float>(
			options.elevationPath,
			cellCount
		);
		PackedBits landMask = readPacked(
			options.landMaskPath,
			cellCount
		);
		PackedBits seaBits = packSeaMask(
			options.seaMaskPath,
			cellCount
		);

		const std::vector<std::uint8_t> threshold =
			solveLandMask(
				elevation,
				landMask,
				seaBits,
				options.width,
				options.height,
				options.levels
			);

		writeBinary(
			options.outputPath,
			threshold
		);
		return 0;
	} catch (const std::exception& error) {
		std::cerr << "Fehler: " << error.what() << "\n";
		return 1;
	}
}
