#include "manifest.hpp"

#include "cache.hpp"
#include "error.hpp"
#include "json.hpp"
#include "paths.hpp"
#include "transport.hpp"

#include <karu/karu.h>

#include <filesystem>
#include <string_view>
#include <vector>

namespace fs = std::filesystem;

namespace taco {
namespace {

constexpr std::uint64_t manifest_limit = 64ULL * 1024 * 1024;

std::optional<fs::path> manifest_local_path(std::string_view candidate) {
    if (!has_uri_scheme(candidate))
        return local_path(candidate);
    if (!candidate.starts_with("file://"))
        return std::nullopt;

    std::string_view path = without_query(candidate).substr(7);
#ifdef _WIN32
    if (path.size() >= 3 && path[0] == '/' && path[2] == ':')
        path.remove_prefix(1);
#endif
    return local_path(path);
}

std::optional<std::string> read_manifest(const std::string& candidate, bool required) {
    if (const auto path = manifest_local_path(candidate)) {
        std::error_code error;
        if (!fs::is_regular_file(*path, error)) {
            if (!required)
                return std::nullopt;
            throw Error(TACO_ERR_NOT_FOUND, "versioned manifest does not exist: " + candidate);
        }
        if (fs::file_size(*path, error) > manifest_limit)
            fail("versioned manifest is larger than 64 MiB, refusing to read it: " + candidate);
        return read_local(*path);
    }
    try {
        return read_object(candidate, manifest_limit, "versioned manifest");
    } catch (const Error& error) {
        // A missing object answers 404, or 403 from buckets that forbid listing.
        const bool absent = error.status() == TACO_ERR_NOT_FOUND || error.transport() == KARU_ERR_AUTH;
        if (!required && absent)
            return std::nullopt;
        throw Error(error.status(), "could not read versioned manifest " + candidate + ": " + error.what());
    }
}

const json::Value& object(const json::Value* value, std::string_view context) {
    if (!value || !value->is_object())
        fail(std::string(context) + " must be an object");
    return *value;
}

void validate_collection(const json::Value& collection, const std::string& version) {
    const std::string prefix = "version '" + version + "' embeds an invalid collection: ";
    std::string missing;
    for (const char* key : {"taco:version", "id", "dataset_version", "description", "licenses", "providers",
                            "tasks", "taco:structure", "taco:metadata"}) {
        if (!collection.find(key))
            missing += (missing.empty() ? "" : ", ") + std::string(key);
    }
    if (!missing.empty())
        fail(prefix + "missing required fields " + missing);
    const json::Value* taco_version = collection.find("taco:version");
    if (!taco_version->is_string() || taco_version->string != "3.0.0")
        fail(prefix + "taco:version must be 3.0.0");
    if (!collection.find("taco:metadata")->is_object())
        fail(prefix + "taco:metadata must be an object");
}

std::string normalize_url_path(std::string_view path) {
    const bool trailing = path.ends_with('/');
    std::vector<std::string_view> segments;
    for (std::size_t start = 0;;) {
        const auto slash = path.find('/', start);
        const auto segment = path.substr(start, slash == std::string_view::npos ? slash : slash - start);
        if (segment == "..") {
            if (!segments.empty())
                segments.pop_back();
        } else if (!segment.empty() && segment != ".") {
            segments.push_back(segment);
        }
        if (slash == std::string_view::npos)
            break;
        start = slash + 1;
    }
    std::string out = "/";
    for (std::size_t i = 0; i < segments.size(); ++i)
        out += (i ? "/" : "") + std::string(segments[i]);
    if (trailing && out != "/")
        out += "/";
    return out;
}

} // namespace

std::optional<std::string> manifest_candidate(const std::string& source) {
    const std::string name = source_name(source);
    if (name == "taco.json")
        return source;
    if (name == ".tacocat" || is_zip_name(name) || is_semver(name))
        return std::nullopt;
    if (source.starts_with("file://")) {
        const std::string candidate = trim_trailing_slashes(without_query(source)) + "/taco.json";
        std::error_code error;
        if (!fs::is_regular_file(*manifest_local_path(candidate), error))
            return std::nullopt;
        return candidate;
    }
    if (has_uri_scheme(source))
        return trim_trailing_slashes(without_query(source)) + "/taco.json";
    std::error_code error;
    const fs::path candidate = local_path(source) / "taco.json";
    if (!fs::is_regular_file(candidate, error))
        return std::nullopt;
    return utf8_path(candidate);
}

std::string join_manifest_href(const std::string& candidate, const std::string& href) {
    if (has_uri_scheme(href))
        return href;
    if (!has_uri_scheme(candidate)) {
        fs::path target = local_path(href);
        if (!target.is_absolute())
            target = local_path(candidate).parent_path() / target;
        return trim_trailing_slashes(utf8_path(target));
    }

    const std::string clean(without_query(candidate));
    if (href.starts_with("//"))
        return clean.substr(0, clean.find(':')) + ":" + href;
    const auto path_start = clean.find('/', clean.find("://") + 3);
    const std::string origin = clean.substr(0, path_start);
    if (href.starts_with('/'))
        return origin + normalize_url_path(href);
    const std::string candidate_path = path_start == std::string::npos ? "/" : clean.substr(path_start);
    return origin + normalize_url_path(candidate_path.substr(0, candidate_path.rfind('/') + 1) + href);
}

std::string resolve_dataset(const std::string& source) {
    const auto direct = [&] {
        return "{\"source\":" + json::quote(source) +
               ",\"collection\":null,\"version\":null,\"versions\":[],\"manifest\":null}";
    };
    const auto candidate = manifest_candidate(source);
    if (!candidate)
        return direct();
    const auto payload = read_manifest(*candidate, source_name(source) == "taco.json");
    if (!payload)
        return direct();

    json::Value manifest;
    try {
        manifest = json::parse(*payload);
    } catch (const json::InvalidJson&) {
        fail("versioned manifest is not valid JSON: " + *candidate);
    }
    object(&manifest, "versioned manifest");
    const json::Value* container = manifest.find("taco:container");
    if (!container || !container->is_string() || container->string != "versioned")
        fail("taco:container must be 'versioned'");
    const json::Value& versions = object(manifest.find("taco:versions"), "taco:versions");
    if (versions.members.empty())
        fail("taco:versions must contain at least one version");
    const json::Value* selected = manifest.find("taco:default_version");
    if (!selected || !selected->is_string() || selected->string.empty())
        fail("taco:default_version must be a non-empty string");
    if (!versions.find(selected->string))
        fail("taco:default_version '" + selected->string + "' is not present in taco:versions");

    std::string names;
    const json::Value* chosen = nullptr;
    std::string href;
    for (const auto& [version, value] : versions.members) {
        if (!is_semver(version))
            fail("taco:versions key '" + version + "' must follow Semantic Versioning");
        const json::Value& entry = object(&value, "version '" + version + "'");
        const json::Value* entry_href = entry.find("href");
        if (!entry_href || !entry_href->is_string() || entry_href->string.empty())
            fail("version '" + version + "' needs a non-empty href");
        const json::Value& collection = object(entry.find("collection"), "version '" + version + "' collection");
        const json::Value* dataset_version = collection.find("dataset_version");
        if (!dataset_version || !dataset_version->is_string() || dataset_version->string != version)
            fail("version '" + version + "' embeds collection dataset_version " +
                 (dataset_version && dataset_version->is_string() ? "'" + dataset_version->string + "'"
                                                                   : std::string("<missing>")));
        names += (names.empty() ? "" : ",") + json::quote(version);
        if (!chosen && version == selected->string) {
            chosen = &collection;
            href = entry_href->string;
        }
    }
    validate_collection(*chosen, selected->string);

    return "{\"source\":" + json::quote(join_manifest_href(*candidate, href)) +
           ",\"collection\":" + std::string(chosen->raw) + ",\"version\":" + json::quote(selected->string) +
           ",\"versions\":[" + names + "],\"manifest\":" + json::quote(*candidate) + "}";
}

} // namespace taco
