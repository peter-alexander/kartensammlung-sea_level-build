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
	std::string reportPath;
	std::uint32_t width = 0;
	std::uint32_t height = 0;
	double maxLevel = 70.0;
};

struct Span {
	std::uint32_t row;
	std::uint32_t left;
	std::uint32_t right;
};

class PackedBits {
public:
	explicit PackedBits(std::size_t bitCount)
		: bitCount_(bitCount),
		  data_((bitCount + 7) / 8, 0) {}

	bool get(std::size_t index) const {
		return (data_[index >> 3] & bitMask(index)) != 0;
	}

	void set(std::size_t index) {
		data_[index >> 3] |= bitMask(index);
	}

	void clear(std::size_t index) {
		data_[index >> 3] &= static_cast<std::uint8_t>(~bitMask(index));
	}

	const std::vector<std::uint8_t>& data() const {
		return data_;
	}

	std::size_t bytes() const {
		return data_.size();
	}

private:
	static std::uint8_t bitMask(std::size_t index) {
		return static_cast<std::uint8_t>(1u << (index & 7u));
	}

	std::size_t bitCount_;
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
			options.elevationPath = requireValue(i, argc, argv, arg);
		} else if (arg == "--sea-mask") {
			options.seaMaskPath = requireValue(i, argc, argv, arg);
		} else if (arg == "--output") {
			options.outputPath = requireValue(i, argc, argv, arg);
		} else if (arg == "--report") {
			options.reportPath = requireValue(i, argc, argv, arg);
		} else if (arg == "--width") {
			options.width = static_cast<std::uint32_t>(
				std::stoul(requireValue(i, argc, argv, arg))
			);
		} else if (arg == "--height") {
			options.height = static_cast<std::uint32_t>(
				std::stoul(requireValue(i, argc, argv, arg))
			);
		} else if (arg == "--max-level") {
			options.maxLevel = std::stod(
				requireValue(i, argc, argv, arg)
			);
		} else {
			throw std::runtime_error("Unbekanntes Argument: " + arg);
		}
	}

	if (
		options.elevationPath.empty()
		|| options.seaMaskPath.empty()
		|| options.outputPath.empty()
		|| options.reportPath.empty()
	) {
		throw std::runtime_error(
			"--elevation, --sea-mask, --output und --report sind erforderlich."
		);
	}
	if (options.width == 0 || options.height == 0) {
		throw std::runtime_error("--width und --height müssen > 0 sein.");
	}
	if (!std::isfinite(options.maxLevel) || options.maxLevel < 0.0) {
		throw std::runtime_error("--max-level muss endlich und >= 0 sein.");
	}

	return options;
}

static void requireExactFileSize(
	const std::string& path,
	std::uint64_t expectedBytes
) {
	std::ifstream input(path, std::ios::binary | std::ios::ate);
	if (!input) {
		throw std::runtime_error("Datei konnte nicht geöffnet werden: " + path);
	}

	const std::uint64_t actual = static_cast<std::uint64_t>(input.tellg());
	if (actual != expectedBytes) {
		throw std::runtime_error(
			"Unerwartete Dateigröße für " + path
			+ ": erwartet=" + std::to_string(expectedBytes)
			+ " tatsächlich=" + std::to_string(actual)
		);
	}
}

static void writeBinary(
	const std::string& path,
	const std::vector<std::uint8_t>& data
) {
	std::ofstream output(path, std::ios::binary);
	if (!output) {
		throw std::runtime_error(
			"Ausgabedatei konnte nicht geöffnet werden: " + path
		);
	}

	output.write(
		reinterpret_cast<const char*>(data.data()),
		static_cast<std::streamsize>(data.size())
	);
	if (!output) {
		throw std::runtime_error(
			"Ausgabedatei konnte nicht vollständig geschrieben werden: " + path
		);
	}
}

static void writeReport(
	const Options& options,
	std::uint64_t cellCount,
	std::uint64_t elevationEligibleCount,
	std::uint64_t candidateCount,
	std::size_t packedBytes,
	std::size_t maxQueuedSpans
) {
	std::ofstream output(options.reportPath);
	if (!output) {
		throw std::runtime_error(
			"Report konnte nicht geöffnet werden: " + options.reportPath
		);
	}

	const double candidatePct = cellCount == 0
		? 0.0
		: static_cast<double>(candidateCount)
			* 100.0
			/ static_cast<double>(cellCount);

	output
		<< "{\n"
		<< "\t\"width\": " << options.width << ",\n"
		<< "\t\"height\": " << options.height << ",\n"
		<< "\t\"cells\": " << cellCount << ",\n"
		<< "\t\"max_level_m\": " << options.maxLevel << ",\n"
		<< "\t\"elevation_or_sea_eligible_cells\": "
		<< elevationEligibleCount << ",\n"
		<< "\t\"candidate_cells\": " << candidateCount << ",\n"
		<< "\t\"candidate_pct\": " << candidatePct << ",\n"
		<< "\t\"packed_mask_bytes\": " << packedBytes << ",\n"
		<< "\t\"max_queued_spans\": " << maxQueuedSpans << "\n"
		<< "}\n";
}

static void buildEligibility(
	const Options& options,
	PackedBits& eligible,
	std::uint64_t& eligibleCount
) {
	const std::size_t cellCount =
		static_cast<std::size_t>(options.width) * options.height;
	constexpr std::size_t chunkCells = 1u << 20;

	std::ifstream elevation(options.elevationPath, std::ios::binary);
	std::ifstream sea(options.seaMaskPath, std::ios::binary);
	if (!elevation || !sea) {
		throw std::runtime_error("Eingabedatei konnte nicht geöffnet werden.");
	}

	std::vector<float> elevationChunk(chunkCells);
	std::vector<std::uint8_t> seaChunk(chunkCells);

	for (std::size_t offset = 0; offset < cellCount; offset += chunkCells) {
		const std::size_t count = std::min(
			chunkCells,
			cellCount - offset
		);

		elevation.read(
			reinterpret_cast<char*>(elevationChunk.data()),
			static_cast<std::streamsize>(count * sizeof(float))
		);
		sea.read(
			reinterpret_cast<char*>(seaChunk.data()),
			static_cast<std::streamsize>(count)
		);
		if (!elevation || !sea) {
			throw std::runtime_error(
				"Eingabedatei konnte nicht vollständig gelesen werden."
			);
		}

		for (std::size_t local = 0; local < count; ++local) {
			const float value = elevationChunk[local];
			const bool isEligible =
				seaChunk[local] != 0
				|| (
					std::isfinite(value)
					&& static_cast<double>(value) <= options.maxLevel
				);

			if (isEligible) {
				eligible.set(offset + local);
				++eligibleCount;
			}
		}
	}
}

static std::uint64_t floodCandidates(
	const Options& options,
	PackedBits& eligible,
	PackedBits& candidate,
	std::size_t& maxQueuedSpans
) {
	const std::size_t width = options.width;
	const std::size_t height = options.height;
	const std::size_t cellCount = width * height;
	constexpr std::size_t chunkCells = 1u << 20;

	std::vector<Span> queue;
	std::size_t queueCursor = 0;
	std::uint64_t candidateCount = 0;

	auto markSpan = [&](std::uint32_t row, std::uint32_t seedCol) {
		const std::size_t rowOffset =
			static_cast<std::size_t>(row) * width;

		std::uint32_t left = seedCol;
		while (
			left > 0
			&& eligible.get(rowOffset + left - 1)
		) {
			--left;
		}

		std::uint32_t right = seedCol;
		while (
			static_cast<std::size_t>(right) + 1 < width
			&& eligible.get(rowOffset + right + 1)
		) {
			++right;
		}

		for (
			std::uint32_t col = left;
			col <= right;
			++col
		) {
			const std::size_t index = rowOffset + col;
			eligible.clear(index);
			candidate.set(index);
			++candidateCount;
		}

		queue.push_back({row, left, right});
		maxQueuedSpans = std::max(
			maxQueuedSpans,
			queue.size() - queueCursor
		);
	};

	auto scanNeighborRow = [&](std::uint32_t row, const Span& parent) {
		const std::size_t rowOffset =
			static_cast<std::size_t>(row) * width;
		std::uint32_t col = parent.left;

		while (col <= parent.right) {
			if (!eligible.get(rowOffset + col)) {
				++col;
				continue;
			}

			markSpan(row, col);

			while (
				col <= parent.right
				&& !eligible.get(rowOffset + col)
			) {
				++col;
			}
		}
	};

	auto drainQueue = [&]() {
		while (queueCursor < queue.size()) {
			const Span span = queue[queueCursor++];

			if (span.row > 0) {
				scanNeighborRow(span.row - 1, span);
			}
			if (
				static_cast<std::size_t>(span.row) + 1 < height
			) {
				scanNeighborRow(span.row + 1, span);
			}

			if (
				queueCursor > (1u << 20)
				&& queueCursor * 2 > queue.size()
			) {
				queue.erase(
					queue.begin(),
					queue.begin() + static_cast<std::ptrdiff_t>(queueCursor)
				);
				queueCursor = 0;
			}
		}

		queue.clear();
		queueCursor = 0;
	};

	std::ifstream sea(options.seaMaskPath, std::ios::binary);
	if (!sea) {
		throw std::runtime_error(
			"Sea-Maske konnte nicht erneut geöffnet werden."
		);
	}

	std::vector<std::uint8_t> seaChunk(chunkCells);

	for (std::size_t offset = 0; offset < cellCount; offset += chunkCells) {
		const std::size_t count = std::min(
			chunkCells,
			cellCount - offset
		);

		sea.read(
			reinterpret_cast<char*>(seaChunk.data()),
			static_cast<std::streamsize>(count)
		);
		if (!sea) {
			throw std::runtime_error(
				"Sea-Maske konnte nicht vollständig gelesen werden."
			);
		}

		for (std::size_t local = 0; local < count; ++local) {
			if (seaChunk[local] == 0) {
				continue;
			}

			const std::size_t index = offset + local;
			if (!eligible.get(index)) {
				continue;
			}

			const std::uint32_t row = static_cast<std::uint32_t>(
				index / width
			);
			const std::uint32_t col = static_cast<std::uint32_t>(
				index - static_cast<std::size_t>(row) * width
			);

			markSpan(row, col);
			drainQueue();
		}
	}

	return candidateCount;
}

int main(int argc, char** argv) {
	try {
		const Options options = parseArgs(argc, argv);
		const std::uint64_t cellCount =
			static_cast<std::uint64_t>(options.width)
			* static_cast<std::uint64_t>(options.height);

		requireExactFileSize(
			options.elevationPath,
			cellCount * sizeof(float)
		);
		requireExactFileSize(
			options.seaMaskPath,
			cellCount
		);

		if (
			cellCount
			> static_cast<std::uint64_t>(
				std::numeric_limits<std::size_t>::max()
			)
		) {
			throw std::runtime_error(
				"Raster ist für diese Plattform zu groß."
			);
		}

		PackedBits eligible(static_cast<std::size_t>(cellCount));
		PackedBits candidate(static_cast<std::size_t>(cellCount));

		std::uint64_t eligibleCount = 0;
		buildEligibility(options, eligible, eligibleCount);

		std::size_t maxQueuedSpans = 0;
		const std::uint64_t candidateCount = floodCandidates(
			options,
			eligible,
			candidate,
			maxQueuedSpans
		);

		writeBinary(options.outputPath, candidate.data());
		writeReport(
			options,
			cellCount,
			eligibleCount,
			candidateCount,
			candidate.bytes(),
			maxQueuedSpans
		);

		std::cerr
			<< "cells=" << cellCount
			<< " eligible=" << eligibleCount
			<< " candidates=" << candidateCount
			<< " candidate_pct="
			<< (
				cellCount == 0
				? 0.0
				: static_cast<double>(candidateCount)
					* 100.0
					/ static_cast<double>(cellCount)
			)
			<< " packed_bytes=" << candidate.bytes()
			<< " max_queued_spans=" << maxQueuedSpans
			<< "\n";

		return 0;
	} catch (const std::exception& error) {
		std::cerr << "Fehler: " << error.what() << "\n";
		return 1;
	}
}
