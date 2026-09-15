#include "dataset.hpp"

#include "cozip_index.hpp"
#include "error.hpp"
#include "json.hpp"
#include "paths.hpp"
#include "transport.hpp"

#include <karu/karu.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <functional>
#include <sstream>
#include <thread>

namespace fs = std::filesystem;

namespace taco {
namespace {

constexpr std::string_view collection_name = "COLLECTION.json";
constexpr std::string_view metadata_prefix = "METADATA/";
constexpr std::string_view parquet_suffix = ".parquet";
constexpr std::string_view supported_version = "3.0.0";
constexpr std::uint64_t collection_limit = 64ULL * 1024 * 1024;
constexpr std::string_view cache_format = "taco-cache 1";

struct Level {
    std::string name;
    // The index entry of a ZIP level, or where a directory level is read from.
    std::string origin;
};

std::string utf8(const fs::path& path) {
    return utf8_path(path);
}

std::size_t level_depth(std::string_view level) {
    return level == "sample" ? 0 : 1 + static_cast<std::size_t>(std::count(level.begin(), level.end(), '/'));
}

void sort_and_validate(std::vector<Level>& levels, const std::string& source) {
    if (levels.empty())
        fail("no METADATA Parquet files found: " + source);
    // Parents come before their children so the join chain resolves.
    std::sort(levels.begin(), levels.end(), [](const Level& a, const Level& b) {
        const auto da = level_depth(a.name);
        const auto db = level_depth(b.name);
        return da != db ? da < db : a.name < b.name;
    });
    if (levels[0].name != "sample")
        fail("TACO dataset has no sample.parquet: " + source);
    for (std::size_t i = 1; i < levels.size(); ++i) {
        const auto& name = levels[i].name;
        if (name != "children" && !name.starts_with("children/"))
            fail("METADATA level '" + name + "' is not 'children' or below it: " + source);
        const auto parent = parent_level(name);
        const auto found = std::find_if(levels.begin(), levels.begin() + static_cast<std::ptrdiff_t>(i),
                                        [&](const Level& level) { return level.name == parent; });
        if (found == levels.begin() + static_cast<std::ptrdiff_t>(i))
            fail("METADATA level '" + name + "' has no parent level '" + parent + "': " + source);
    }
    if (levels.size() > 1 && levels[1].name != "children")
        fail("TACO dataset has child levels but no children.parquet: " + source);
}

// Local paths stay as the caller wrote them. URIs take karu's canonical form,
// and HTTP keeps the /vsicurl/ prefix that GDAL expects.
std::string location_base(const std::string& path) {
    if (!has_uri_scheme(path))
        return path;
    std::string canonical = canonical_uri(path);
    if (canonical.starts_with("http://") || canonical.starts_with("https://"))
        return "/vsicurl/" + canonical;
    return canonical;
}

std::string read_local(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream)
        throw Error(TACO_ERR_IO, "could not read " + utf8(path));
    std::ostringstream out;
    out << stream.rdbuf();
    return out.str();
}

std::string unique_suffix() {
    static std::atomic<std::uint64_t> counter{0};
    const auto now = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto thread = std::hash<std::thread::id>{}(std::this_thread::get_id());
    return hex64(fnv1a64(std::to_string(now) + ":" + std::to_string(thread) + ":" +
                         std::to_string(counter.fetch_add(1))));
}

void write_atomically(const fs::path& target, std::string_view bytes) {
    fs::path temporary = target;
    temporary += ".tmp-" + unique_suffix();
    {
        std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
        stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
        if (!stream)
            throw Error(TACO_ERR_IO, "could not write the metadata cache: " + utf8(temporary));
    }
    std::error_code error;
    fs::rename(temporary, target, error);
    if (error) {
        std::error_code ignored;
        fs::remove(temporary, ignored);
        throw Error(TACO_ERR_IO, "could not write the metadata cache " + utf8(target) + ": " + error.message());
    }
}

// One directory per dataset version. A version never overwrites another, so
// concurrent readers of different versions cannot mix their files.
class Cache {
  public:
    Cache(const std::string& root, const std::string& identity, const std::string& key,
          std::vector<std::string> files)
        : directory_(local_path(root) / hex64(fnv1a64(identity + "\n" + key))),
          stamp_(std::string(cache_format) + "\n" + identity + "\n" + key + "\n"),
          files_(std::move(files)) {}

    [[nodiscard]] bool complete() const {
        std::error_code error;
        for (const auto& file : files_) {
            if (!fs::is_regular_file(directory_ / local_path(file), error))
                return false;
        }
        if (!fs::is_regular_file(directory_ / "stamp", error))
            return false;
        return read_local(directory_ / "stamp") == stamp_;
    }

    void store(const std::vector<std::string>& contents) const {
        std::error_code error;
        fs::create_directories(directory_, error);
        if (error)
            throw Error(TACO_ERR_IO, "could not create the metadata cache " + utf8(directory_) + ": " +
                                         error.message());
        for (std::size_t i = 0; i < files_.size(); ++i)
            write_atomically(directory_ / local_path(files_[i]), contents[i]);
        // The stamp is written last and marks the directory as complete.
        write_atomically(directory_ / "stamp", stamp_);
    }

    [[nodiscard]] std::string path(std::string_view file) const {
        return utf8(directory_ / local_path(file));
    }

  private:
    fs::path directory_;
    std::string stamp_;
    std::vector<std::string> files_;
};

std::string cache_identity(const std::string& source) {
    if (has_uri_scheme(source))
        return canonical_uri(source);
    std::error_code error;
    const auto absolute = fs::absolute(local_path(source), error);
    return error ? source : utf8(absolute.lexically_normal());
}

Dataset open_zip(const std::string& source, const std::string& cache_root) {
    const CozipIndex index = read_cozip_index(source);
    if (index.profile != cozip_profile_taco)
        fail("taco needs a TACO-profile archive (profile=2). Got profile=" + profile_name(index.profile) +
             " in: " + source);
    const CozipEntry* collection = index.find(collection_name);
    if (!collection)
        fail("TACO archive has no COLLECTION.json in its cozip index: " + source);
    if (collection->size > collection_limit)
        fail("COLLECTION.json is larger than 64 MiB, refusing to read it: " + source);

    std::vector<Level> levels;
    for (const auto& entry : index.entries) {
        if (entry.name.starts_with(metadata_prefix) && entry.name.ends_with(parquet_suffix))
            levels.push_back(Level{file_to_level(entry.name.substr(metadata_prefix.size())), entry.name});
    }
    sort_and_validate(levels, source);

    std::vector<std::string> files = {std::string(collection_name)};
    for (const auto& level : levels)
        files.push_back(level_to_file(level.name));
    const Cache cache(cache_root, cache_identity(source),
                      "zip " + std::to_string(index.file_size) + " " + hex64(index.integrity), files);
    if (!cache.complete()) {
        std::vector<Range> ranges = {Range{source, collection->offset, collection->size}};
        for (const auto& level : levels) {
            const CozipEntry* entry = index.find(level.origin);
            ranges.push_back(Range{source, entry->offset, entry->size});
        }
        cache.store(read_ranges(ranges));
    }

    Dataset dataset;
    dataset.source = source;
    dataset.container = Container::zip;
    dataset.location_base = location_base(source);
    dataset.collection = read_local(local_path(cache.path(collection_name)));
    for (const auto& level : levels) {
        dataset.level_names.push_back(level.name);
        dataset.level_paths.push_back(cache.path(level_to_file(level.name)));
    }
    return dataset;
}

Dataset open_local_directory(const std::string& source) {
    const std::string directory = trim_trailing_slashes(source);
    const fs::path root = local_path(directory);
    std::error_code error;
    if (!fs::is_regular_file(root / collection_name, error))
        fail("directory has no COLLECTION.json: " + directory);

    // TACO spec 7.5: a catalog sits beside the archives it indexes, so
    // internal:source_file resolves against its parent directory.
    const bool folder = fs::is_directory(root / "METADATA", error);
    Dataset dataset;
    dataset.source = directory;
    dataset.container = folder ? Container::folder : Container::tacocat;
    dataset.location_base = folder ? directory : parent_path(directory);

    std::vector<Level> levels;
    const fs::path parquet_directory = folder ? root / "METADATA" : root;
    for (const auto& entry : fs::directory_iterator(parquet_directory, error)) {
        const std::string name = utf8(entry.path().filename());
        if (entry.is_regular_file(error) && name.ends_with(parquet_suffix))
            levels.push_back(Level{file_to_level(name), utf8(entry.path())});
    }
    if (error)
        throw Error(TACO_ERR_IO, "could not list " + utf8(parquet_directory) + ": " + error.message());
    sort_and_validate(levels, directory);

    if (fs::file_size(root / collection_name, error) > collection_limit)
        fail("COLLECTION.json is larger than 64 MiB, refusing to read it: " + directory);
    dataset.collection = read_local(root / collection_name);
    for (const auto& level : levels) {
        dataset.level_names.push_back(level.name);
        dataset.level_paths.push_back(level.origin);
    }
    return dataset;
}

json::Value parse_collection(const std::string& text, const std::string& source) {
    try {
        json::Value root = json::parse(text);
        if (!root.is_object())
            fail("COLLECTION.json must be a JSON object: " + source);
        return root;
    } catch (const json::InvalidJson&) {
        fail("COLLECTION.json is not valid JSON: " + source);
    }
}

// Object stores cannot list directories reliably. The Parquet files come from
// the levels declared in COLLECTION.json, and taco:sources marks a TACOCAT.
Dataset open_uri_directory(const std::string& source, const std::string& cache_root) {
    const std::string directory = trim_trailing_slashes(without_query(source));
    const std::string location = remote_directory(directory);
    Dataset dataset;
    dataset.source = directory;
    dataset.collection = read_object(child_path(directory, collection_name), collection_limit, "COLLECTION.json");

    const json::Value root = parse_collection(dataset.collection, directory);
    const json::Value* metadata = root.find("taco:metadata");
    if (!metadata || !metadata->is_object())
        fail("COLLECTION.json has no valid taco:metadata object: " + directory);
    const json::Value* sources = root.find("taco:sources");
    if (sources && !sources->is_object())
        fail("COLLECTION.json has an invalid taco:sources object: " + directory);

    const bool tacocat = sources != nullptr;
    dataset.container = tacocat ? Container::tacocat : Container::folder;
    dataset.location_base = tacocat ? parent_path(location) : location;
    const std::string parquet_directory = tacocat ? directory : child_path(directory, "METADATA");

    std::vector<Level> levels;
    for (const auto& [name, value] : metadata->members)
        levels.push_back(Level{name, child_path(parquet_directory, level_to_file(name))});
    sort_and_validate(levels, directory);

    std::string key = "directory " + hex64(fnv1a64(dataset.collection));
    std::vector<std::string> files;
    std::vector<Range> ranges;
    for (const auto& level : levels) {
        const std::uint64_t size = object_size(level.origin);
        key += " " + std::to_string(size);
        files.push_back(level_to_file(level.name));
        ranges.push_back(Range{level.origin, 0, size});
    }
    const Cache cache(cache_root, location, key, files);
    if (!cache.complete())
        cache.store(read_ranges(ranges));
    for (const auto& level : levels) {
        dataset.level_names.push_back(level.name);
        dataset.level_paths.push_back(cache.path(level_to_file(level.name)));
    }
    return dataset;
}

bool is_remote_cozip(const std::string& source) {
    try {
        (void)read_cozip_profile(source);
        return true;
    } catch (const Error& error) {
        // A missing object may be a directory URL. Format failures mean the
        // object is not a CoZIP archive. Authentication, network, TLS and
        // server failures must keep their original diagnostic.
        if (error.transport() == KARU_ERR_NOT_FOUND || error.transport() == 0)
            return false;
        throw;
    }
}

bool is_explicit_remote_directory(std::string_view source) {
    const auto object = without_query(source);
    if (object.ends_with('/') || source_name(source) == ".tacocat")
        return true;
    if (!object.starts_with("file://"))
        return false;
    auto path = object.substr(7);
#ifdef _WIN32
    if (path.size() >= 3 && path[0] == '/' && path[2] == ':')
        path.remove_prefix(1);
#endif
    std::error_code error;
    return fs::is_directory(local_path(path), error);
}

Contract read_contract(const Dataset& dataset) {
    const std::string& source = dataset.source;
    const json::Value root = parse_collection(dataset.collection, source);

    Contract contract;
    const json::Value* version = root.find("taco:version");
    if (!version || !version->is_string())
        fail("COLLECTION.json has no valid taco:version: " + source);
    if (version->string != supported_version)
        fail("unsupported TACO version '" + version->string + "' in " + source + "; expected " +
             std::string(supported_version));

    const json::Value* structure = root.find("taco:structure");
    if (!structure)
        fail("COLLECTION.json has no taco:structure key: " + source);
    // TACO spec 5.2: null means every sample is a single file.
    contract.null_structure = structure->is_null();
    if (!contract.null_structure) {
        if (!structure->is_array())
            fail("COLLECTION.json: taco:structure must be an array or null: " + source);
        for (const auto& item : structure->items) {
            if (!item.is_string())
                fail("COLLECTION.json: taco:structure must contain strings: " + source);
            contract.structure.push_back(item.string);
        }
    }

    // taco:metadata names the user columns of every level. The reader needs
    // them to resolve a field declared at two levels of the same branch.
    const json::Value* metadata = root.find("taco:metadata");
    if (!metadata || !metadata->is_object())
        fail("COLLECTION.json has no valid taco:metadata object: " + source);
    for (const auto& [level, value] : metadata->members) {
        if (!value.is_object())
            fail("COLLECTION.json: metadata level must be an object: " + source);
        std::vector<std::string> names;
        for (const auto& member : value.members)
            names.push_back(member.first);
        contract.fields.emplace_back(level, std::move(names));
    }
    for (const auto& level : dataset.level_names) {
        if (!contract.fields_of(level))
            fail("COLLECTION.json has no metadata declaration for level '" + level + "': " + source);
    }
    if (contract.fields.size() != dataset.level_names.size())
        fail("COLLECTION.json metadata levels do not match its Parquet files: " + source);
    if (contract.null_structure != (dataset.level_names.size() == 1))
        fail("COLLECTION.json structure does not match its metadata levels: " + source);

    if (const json::Value* derived = root.find("taco:derived")) {
        if (!derived->is_object())
            fail("COLLECTION.json: taco:derived must be an object: " + source);
        contract.has_derived = true;
        contract.derived = std::string(derived->raw);
    }
    return contract;
}

} // namespace

const std::vector<std::string>* Contract::fields_of(std::string_view level) const {
    for (const auto& [name, names] : fields) {
        if (name == level)
            return &names;
    }
    return nullptr;
}

std::size_t Dataset::level_index(std::string_view name) const {
    for (std::size_t i = 0; i < level_names.size(); ++i) {
        if (level_names[i] == name)
            return i;
    }
    fail("TACO dataset has no level '" + std::string(name) + "': " + source);
}

std::string remote_directory(const std::string& directory) {
    return parent_path(location_base(child_path(directory, collection_name)));
}

Dataset open_dataset(const std::string& source, const std::string& cache_dir) {
    if (source.empty())
        fail("taco: path must not be empty");
    const std::string cache_root = cache_dir.empty() ? default_cache_dir() : cache_dir;

    Dataset dataset;
    std::error_code error;
    if (has_uri_scheme(source)) {
        const bool archive = is_zip_name(source) ||
                             (!is_explicit_remote_directory(source) && is_remote_cozip(source));
        dataset = archive ? open_zip(source, cache_root) : open_uri_directory(source, cache_root);
    }
    else if (fs::is_directory(local_path(source), error))
        dataset = open_local_directory(source);
    else
        dataset = open_zip(source, cache_root);
    dataset.contract = read_contract(dataset);
    return dataset;
}

const char* container_name(Container container) noexcept {
    switch (container) {
    case Container::zip:
        return "zip";
    case Container::folder:
        return "folder";
    case Container::tacocat:
        return "tacocat";
    }
    return "zip";
}

} // namespace taco
