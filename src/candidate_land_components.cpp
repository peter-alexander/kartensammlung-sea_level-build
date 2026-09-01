#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

struct Options {
	std::string candidatePath;
	std::string seaMaskPath;
	std::string reportPath;
	std::uint32_t width = 0;
	std::uint32_t height = 0;
};

struct Span {
	std::uint32_t row;
	std::uint32_t left;
	std::uint32_t right;
};

struct Component {
	std::uint64_t cells = 0;
	std::uint64_t coastalCells = 0;
	std::uint32_t minRow = 0;
	std::uint32_t maxRow = 0;
	std::uint32_t minCol = 0;
	std::uint32_t maxCol = 0;
};

class PackedBits {
public:
	PackedBits() = default;

	explicit PackedBits(std::size_t bitCount)
		: bitCount_(bitCount),
		  data_((bitCount + 7) / 8, 0) {}

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

	void clear(std::size_t index) {
		data_[index >> 3] &= static_cast<std::uint8_t>(
			~static_cast<std::uint8_t>(1u << (index & 7u))
		);
	}

	std::vector<std::uint8_t>& data() {
		return data_;
	}

	const std::vector<std::uint8_t>& data() const {
		return data_;
	}

	std::size_t bytes() const {
		return data_.size();
	}

private:
	std::size_t bitCount_ = 0;
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

		if (arg == "--candidate-mask") {
			options.candidatePath = requireValue(
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
		} else if (arg == "--report") {
			options.reportPath = requireValue(
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
		} else {
			throw std::runtime_error(
				"Unbekanntes Argument: " + arg
			);
		}
	}

	if (
		options.candidatePath.empty()
		|| options.seaMaskPath.empty()
		|| options.reportPath.empty()
	) {
		throw std::runtime_error(
			"--candidate-mask, --sea-mask und --report "
			"sind erforderlich."
		);
	}
	if (options.width == 0 || options.height == 0) {
		throw std::runtime_error(
			"--width und --height müssen > 0 sein."
		);
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

static PackedBits loadCandidateBits(
	const std::string& path,
	std::size_t cellCount
) {
	PackedBits bits(cellCount);
	const std::size_t expectedBytes = bits.bytes();

	if (fileSize(path) != expectedBytes) {
		throw std::runtime_error(
			"Unerwartete Candidate-Dateigröße."
		);
	}

	std::ifstream input(path, std::ios::binary);
	input.read(
		reinterpret_cast<char*>(bits.data().data()),
		static_cast<std::streamsize>(expectedBytes)
	);
	if (!input) {
		throw std::runtime_error(
			"Candidate-Maske konnte nicht vollständig "
			"gelesen werden."
		);
	}

	return bits;
}

static PackedBits removeSeaAndPack(
	PackedBits& landCandidate,
	const std::string& seaMaskPath,
	std::size_t cellCount,
	std::uint64_t& seaCandidateCells,
	std::uint64_t& landCandidateCells
) {
	if (fileSize(seaMaskPath) != cellCount) {
		throw std::runtime_error(
			"Unerwartete Sea-Mask-Dateigröße."
		);
	}

	PackedBits seaBits(cellCount);
	constexpr std::size_t chunkCells = 1u << 20;
	std::vector<std::uint8_t> chunk(chunkCells);

	std::ifstream sea(seaMaskPath, std::ios::binary);
	if (!sea) {
		throw std::runtime_error(
			"Sea-Maske konnte nicht geöffnet werden."
		);
	}

	for (
		std::size_t offset = 0;
		offset < cellCount;
		offset += chunkCells
	) {
		const std::size_t count = std::min(
			chunkCells,
			cellCount - offset
		);

		sea.read(
			reinterpret_cast<char*>(chunk.data()),
			static_cast<std::streamsize>(count)
		);
		if (!sea) {
			throw std::runtime_error(
				"Sea-Maske konnte nicht vollständig "
				"gelesen werden."
			);
		}

		for (std::size_t local = 0; local < count; ++local) {
			const std::size_t index = offset + local;

			if (chunk[local] != 0) {
				seaBits.set(index);
				if (landCandidate.get(index)) {
					++seaCandidateCells;
					landCandidate.clear(index);
				}
			} else if (landCandidate.get(index)) {
				++landCandidateCells;
			}
		}
	}

	return seaBits;
}

static bool touchesSea(
	const PackedBits& seaBits,
	std::size_t index,
	std::size_t width,
	std::size_t height
) {
	const std::size_t row = index / width;
	const std::size_t col = index - row * width;

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

static Component floodComponent(
	PackedBits& remaining,
	const PackedBits& seaBits,
	std::uint32_t seedRow,
	std::uint32_t seedCol,
	std::uint32_t width,
	std::uint32_t height,
	std::size_t& maxQueuedSpans
) {
	Component component;
	component.minRow = seedRow;
	component.maxRow = seedRow;
	component.minCol = seedCol;
	component.maxCol = seedCol;

	std::vector<Span> queue;
	std::size_t cursor = 0;

	auto markSpan = [&](std::uint32_t row, std::uint32_t col) {
		const std::size_t rowOffset =
			static_cast<std::size_t>(row) * width;

		std::uint32_t left = col;
		while (
			left > 0
			&& remaining.get(rowOffset + left - 1)
		) {
			--left;
		}

		std::uint32_t right = col;
		while (
			right + 1 < width
			&& remaining.get(rowOffset + right + 1)
		) {
			++right;
		}

		for (
			std::uint32_t x = left;
			x <= right;
			++x
		) {
			const std::size_t index = rowOffset + x;
			remaining.clear(index);
			++component.cells;

			if (
				touchesSea(
					seaBits,
					index,
					width,
					height
				)
			) {
				++component.coastalCells;
			}
		}

		component.minRow = std::min(
			component.minRow,
			row
		);
		component.maxRow = std::max(
			component.maxRow,
			row
		);
		component.minCol = std::min(
			component.minCol,
			left
		);
		component.maxCol = std::max(
			component.maxCol,
			right
		);

		queue.push_back({row, left, right});
		maxQueuedSpans = std::max(
			maxQueuedSpans,
			queue.size() - cursor
		);
	};

	auto scanRow = [&](std::uint32_t row, const Span& parent) {
		const std::size_t rowOffset =
			static_cast<std::size_t>(row) * width;
		std::uint32_t col = parent.left;

		while (col <= parent.right) {
			if (!remaining.get(rowOffset + col)) {
				++col;
				continue;
			}

			markSpan(row, col);

			while (
				col <= parent.right
				&& !remaining.get(rowOffset + col)
			) {
				++col;
			}
		}
	};

	markSpan(seedRow, seedCol);

	while (cursor < queue.size()) {
		const Span span = queue[cursor++];

		if (span.row > 0) {
			scanRow(span.row - 1, span);
		}
		if (span.row + 1 < height) {
			scanRow(span.row + 1, span);
		}

		if (
			cursor > (1u << 20)
			&& cursor * 2 > queue.size()
		) {
			queue.erase(
				queue.begin(),
				queue.begin()
					+ static_cast<std::ptrdiff_t>(cursor)
			);
			cursor = 0;
		}
	}

	return component;
}

static std::vector<Component> findComponents(
	PackedBits& remaining,
	const PackedBits& seaBits,
	std::uint32_t width,
	std::uint32_t height,
	std::size_t& maxQueuedSpans
) {
	const std::size_t cellCount =
		static_cast<std::size_t>(width) * height;
	std::vector<Component> components;

	for (std::size_t index = 0; index < cellCount; ++index) {
		if (!remaining.get(index)) {
			continue;
		}

		const std::uint32_t row =
			static_cast<std::uint32_t>(index / width);
		const std::uint32_t col =
			static_cast<std::uint32_t>(
				index
				- static_cast<std::size_t>(row) * width
			);

		components.push_back(
			floodComponent(
				remaining,
				seaBits,
				row,
				col,
				width,
				height,
				maxQueuedSpans
			)
		);
	}

	std::sort(
		components.begin(),
		components.end(),
		[](const Component& a, const Component& b) {
			return a.cells > b.cells;
		}
	);

	return components;
}

static void writeReport(
	const Options& options,
	std::uint64_t seaCandidateCells,
	std::uint64_t landCandidateCells,
	const std::vector<Component>& components,
	std::size_t packedBytes,
	std::size_t maxQueuedSpans
) {
	std::ofstream output(options.reportPath);
	if (!output) {
		throw std::runtime_error(
			"Report konnte nicht geöffnet werden."
		);
	}

	const std::uint64_t largest = (
		components.empty()
			? 0
			: components.front().cells
	);
	const double largestPct = landCandidateCells == 0
		? 0.0
		: static_cast<double>(largest)
			* 100.0
			/ static_cast<double>(landCandidateCells);

	output
		<< "{\n"
		<< "\t\"width\": " << options.width << ",\n"
		<< "\t\"height\": " << options.height << ",\n"
		<< "\t\"sea_candidate_cells\": "
		<< seaCandidateCells << ",\n"
		<< "\t\"land_candidate_cells\": "
		<< landCandidateCells << ",\n"
		<< "\t\"component_count\": "
		<< components.size() << ",\n"
		<< "\t\"largest_component_cells\": "
		<< largest << ",\n"
		<< "\t\"largest_component_pct_of_land_candidates\": "
		<< largestPct << ",\n"
		<< "\t\"packed_bytes_each_mask\": "
		<< packedBytes << ",\n"
		<< "\t\"max_queued_spans\": "
		<< maxQueuedSpans << ",\n"
		<< "\t\"components\": [\n";

	for (std::size_t i = 0; i < components.size(); ++i) {
		const Component& c = components[i];
		const double pct = landCandidateCells == 0
			? 0.0
			: static_cast<double>(c.cells)
				* 100.0
				/ static_cast<double>(landCandidateCells);

		output
			<< "\t\t{\n"
			<< "\t\t\t\"rank\": " << (i + 1) << ",\n"
			<< "\t\t\t\"cells\": " << c.cells << ",\n"
			<< "\t\t\t\"pct_of_land_candidates\": "
			<< pct << ",\n"
			<< "\t\t\t\"coastal_cells\": "
			<< c.coastalCells << ",\n"
			<< "\t\t\t\"bbox_cells\": ["
			<< c.minCol << ", "
			<< c.minRow << ", "
			<< c.maxCol << ", "
			<< c.maxRow << "],\n"
			<< "\t\t\t\"bbox_width\": "
			<< (c.maxCol - c.minCol + 1) << ",\n"
			<< "\t\t\t\"bbox_height\": "
			<< (c.maxRow - c.minRow + 1) << "\n"
			<< "\t\t}";

		if (i + 1 != components.size()) {
			output << ",";
		}
		output << "\n";
	}

	output
		<< "\t]\n"
		<< "}\n";
}

int main(int argc, char** argv) {
	try {
		const Options options = parseArgs(argc, argv);
		const std::size_t cellCount =
			static_cast<std::size_t>(options.width)
			* options.height;

		PackedBits remaining = loadCandidateBits(
			options.candidatePath,
			cellCount
		);

		std::uint64_t seaCandidateCells = 0;
		std::uint64_t landCandidateCells = 0;
		PackedBits seaBits = removeSeaAndPack(
			remaining,
			options.seaMaskPath,
			cellCount,
			seaCandidateCells,
			landCandidateCells
		);

		std::size_t maxQueuedSpans = 0;
		std::vector<Component> components = findComponents(
			remaining,
			seaBits,
			options.width,
			options.height,
			maxQueuedSpans
		);

		std::uint64_t sum = 0;
		for (const Component& component : components) {
			sum += component.cells;
		}
		if (sum != landCandidateCells) {
			throw std::runtime_error(
				"Komponentensumme stimmt nicht mit "
				"Land-Candidate-Zahl überein."
			);
		}

		writeReport(
			options,
			seaCandidateCells,
			landCandidateCells,
			components,
			remaining.bytes(),
			maxQueuedSpans
		);

		std::cerr
			<< "land_candidate_cells="
			<< landCandidateCells
			<< " components=" << components.size()
			<< " largest="
			<< (
				components.empty()
					? 0
					: components.front().cells
			)
			<< " max_queued_spans="
			<< maxQueuedSpans
			<< "\n";

		return 0;
	} catch (const std::exception& error) {
		std::cerr << "Fehler: " << error.what() << "\n";
		return 1;
	}
}
