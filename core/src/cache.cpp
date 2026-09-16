#include "cache.hpp"

#include "error.hpp"
#include "json.hpp"
#include "paths.hpp"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <functional>
#include <memory>
#include <sstream>
#include <thread>

namespace fs = std::filesystem;

namespace taco {
namespace {

constexpr std::string_view stamp_name = "taco-cache.json";
constexpr std::uint64_t default_cache_size = 10ULL * 1024 * 1024 * 1024;
constexpr std::string_view cachedir_tag =
    "Signature: 8a477f597d28d172789f06886806bc55\n"
    "# This directory holds metadata that taco can download again.\n"
    "# See https://bford.info/cachedir/\n";

std::string environment(const char* name) {
#if defined(_WIN32)
    char* value = nullptr;
    std::size_t size = 0;
    if (_dupenv_s(&value, &size, name) != 0)
        return {};
    const std::unique_ptr<char, decltype(&std::free)> owned(value, &std::free);
    return owned ? std::string(owned.get()) : std::string();
#else
    const char* value = std::getenv(name);
    return value ? std::string(value) : std::string();
#endif
}

bool refreshing() {
    return !environment("TACO_CACHE_REFRESH").empty();
}

std::uint64_t cache_size_cap() {
    const std::string value = environment("TACO_CACHE_SIZE");
    if (value.empty())
        return default_cache_size;
    char* end = nullptr;
    const auto parsed = std::strtoull(value.c_str(), &end, 10);
    if (end == value.c_str() || *end != '\0')
        fail(std::string("TACO_CACHE_SIZE must be a number of bytes, got ") + value);
    return parsed;
}

std::string unique_suffix() {
    static std::atomic<std::uint64_t> counter{0};
    const auto now = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto thread = std::hash<std::thread::id>{}(std::this_thread::get_id());
    return hex64(fnv1a64(std::to_string(now) + ":" + std::to_string(thread) + ":" +
                         std::to_string(counter.fetch_add(1))));
}

std::string now_utc() {
    const std::time_t now = std::time(nullptr);
    std::tm parts{};
#ifdef _WIN32
    gmtime_s(&parts, &now);
#else
    gmtime_r(&now, &parts);
#endif
    char text[32];
    std::strftime(text, sizeof text, "%Y-%m-%dT%H:%M:%SZ", &parts);
    return text;
}

std::string stamp_json(const CacheStamp& stamp) {
    return "{\"source\":" + json::quote(stamp.source) + ",\"container\":" + json::quote(stamp.container) +
           ",\"key\":" + json::quote(stamp.key) + ",\"size\":" + std::to_string(stamp.size) +
           ",\"created\":" + json::quote(stamp.created) + ",\"opened\":" + json::quote(stamp.opened) + "}\n";
}

std::optional<CacheStamp> parse_stamp(const std::string& text) {
    json::Value value;
    try {
        value = json::parse(text);
    } catch (const json::InvalidJson&) {
        return std::nullopt;
    }
    if (!value.is_object())
        return std::nullopt;
    CacheStamp stamp;
    for (auto [name, field] : {std::pair{"source", &stamp.source}, std::pair{"container", &stamp.container},
                               std::pair{"key", &stamp.key}, std::pair{"created", &stamp.created},
                               std::pair{"opened", &stamp.opened}}) {
        const json::Value* item = value.find(name);
        if (!item || !item->is_string())
            return std::nullopt;
        *field = item->string;
    }
    const json::Value* size = value.find("size");
    if (!size || size->kind != json::Kind::number)
        return std::nullopt;
    stamp.size = std::strtoull(std::string(size->raw).c_str(), nullptr, 10);
    return stamp;
}

// Moves a directory out of the way before deleting it, so a reader that
// still has it open is not left with half a directory.
void discard(const fs::path& directory) {
    fs::path trash = directory.parent_path() / (".trash-" + unique_suffix());
    std::error_code error;
    fs::rename(directory, trash, error);
    fs::remove_all(error ? directory : trash, error);
}

} // namespace

std::string read_local(const fs::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream)
        throw Error(TACO_ERR_IO, "could not read " + utf8_path(path));
    std::ostringstream out;
    out << stream.rdbuf();
    return out.str();
}

void write_atomically(const fs::path& target, std::string_view bytes) {
    fs::path temporary = target;
    temporary += ".tmp-" + unique_suffix();
    {
        std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
        stream.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
        if (!stream)
            throw Error(TACO_ERR_IO, "could not write the metadata cache: " + utf8_path(temporary));
    }
    std::error_code error;
    fs::rename(temporary, target, error);
    if (error) {
        std::error_code ignored;
        fs::remove(temporary, ignored);
        throw Error(TACO_ERR_IO, "could not write the metadata cache " + utf8_path(target) + ": " + error.message());
    }
}

std::string cache_label(std::string_view text) {
    std::string out;
    for (const char c : text.substr(0, 64)) {
        const bool plain = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '.' ||
                           c == '_';
        out += plain ? c : '-';
    }
    return out.empty() ? "dataset" : out;
}

std::string cache_origin(std::string_view source) {
    if (!has_uri_scheme(source))
        return "local";
    std::string scheme(source.substr(0, source.find("://")));
    std::transform(scheme.begin(), scheme.end(), scheme.begin(), [](unsigned char c) { return std::tolower(c); });
    return scheme;
}

CacheEntry::CacheEntry(const std::string& root, const std::string& identity)
    : root_(local_path(root)), hash_(hex64(fnv1a64(identity)).substr(4)) {}

std::optional<CacheStamp> CacheEntry::find(const std::vector<std::string>& files, std::string_view key) {
    if (refreshing())
        return std::nullopt;
    std::error_code error;
    const std::string suffix = "-" + hash_;
    for (const auto& item : fs::directory_iterator(root_, error)) {
        const std::string name = utf8_path(item.path().filename());
        if (!name.ends_with(suffix) || !item.is_directory(error))
            continue;
        if (!fs::is_regular_file(item.path() / stamp_name, error))
            continue;
        auto stamp = parse_stamp(read_local(item.path() / stamp_name));
        if (!stamp || (!key.empty() && stamp->key != key))
            continue;
        const bool complete = std::all_of(files.begin(), files.end(), [&](const std::string& file) {
            return fs::is_regular_file(item.path() / local_path(file), error);
        });
        if (!complete)
            continue;
        directory_ = item.path();
        stamp->opened = now_utc();
        // A read-only cache still serves its entries.
        try {
            write_atomically(directory_ / stamp_name, stamp_json(*stamp));
        } catch (const Error&) {
        }
        return stamp;
    }
    return std::nullopt;
}

void CacheEntry::store(const std::string& label, const std::vector<std::pair<std::string, std::string>>& files,
                       CacheStamp stamp) {
    std::error_code error;
    fs::create_directories(root_, error);
    if (error)
        throw Error(TACO_ERR_IO, "could not create the metadata cache " + utf8_path(root_) + ": " + error.message());
    if (!fs::exists(root_ / "CACHEDIR.TAG", error))
        write_atomically(root_ / "CACHEDIR.TAG", cachedir_tag);

    // The entry is assembled aside and swapped in, so a reader never sees it
    // half written.
    const fs::path staging = root_ / (".tmp-" + unique_suffix());
    fs::create_directories(staging, error);
    stamp.size = 0;
    for (const auto& [name, content] : files) {
        const fs::path target = staging / local_path(name);
        fs::create_directories(target.parent_path(), error);
        write_atomically(target, content);
        stamp.size += content.size();
    }
    stamp.created = now_utc();
    stamp.opened = stamp.created;
    write_atomically(staging / stamp_name, stamp_json(stamp));

    const std::string suffix = "-" + hash_;
    for (const auto& item : fs::directory_iterator(root_, error)) {
        if (utf8_path(item.path().filename()).ends_with(suffix) && item.is_directory(error))
            discard(item.path());
    }
    directory_ = root_ / (label + suffix);
    fs::rename(staging, directory_, error);
    if (error) {
        discard(staging);
        throw Error(TACO_ERR_IO, "could not write the metadata cache " + utf8_path(directory_) + ": " + error.message());
    }

    // Least recently opened entries make room, never the one just written.
    const std::uint64_t cap = cache_size_cap();
    if (cap == 0)
        return;
    struct Known {
        fs::path directory;
        CacheStamp stamp;
    };
    std::vector<Known> entries;
    std::uint64_t total = 0;
    for (const auto& item : fs::directory_iterator(root_, error)) {
        if (!item.is_directory(error) || !fs::is_regular_file(item.path() / stamp_name, error))
            continue;
        if (auto known = parse_stamp(read_local(item.path() / stamp_name))) {
            total += known->size;
            entries.push_back(Known{item.path(), *known});
        }
    }
    std::sort(entries.begin(), entries.end(),
              [](const Known& a, const Known& b) { return a.stamp.opened < b.stamp.opened; });
    for (const auto& entry : entries) {
        if (total <= cap)
            break;
        if (entry.directory == directory_)
            continue;
        discard(entry.directory);
        total -= entry.stamp.size;
    }
}

std::string CacheEntry::path(std::string_view file) const {
    return utf8_path(directory_ / local_path(file));
}

std::vector<std::string> CacheEntry::parquet_files() const {
    std::vector<std::string> names;
    std::error_code error;
    for (const auto& entry : fs::directory_iterator(directory_ / "METADATA", error)) {
        const std::string name = utf8_path(entry.path().filename());
        if (entry.is_regular_file(error) && name.ends_with(".parquet"))
            names.push_back(name);
    }
    std::sort(names.begin(), names.end());
    return names;
}

} // namespace taco
