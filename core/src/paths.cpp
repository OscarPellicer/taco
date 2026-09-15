#include "paths.hpp"

#include <algorithm>
#include <cstdlib>
#include <regex>
#include <set>

namespace taco {
namespace {

constexpr std::string_view parquet_suffix = ".parquet";

bool is_separator(char c) noexcept {
    return c == '/' || c == '\\';
}

std::string environment(const char* name) {
    const char* value = std::getenv(name);
    return value ? std::string(value) : std::string();
}

std::string replace_all(std::string_view text, std::string_view from, std::string_view to) {
    std::string out;
    std::size_t start = 0;
    for (std::size_t found; (found = text.find(from, start)) != std::string_view::npos;
         start = found + from.size()) {
        out.append(text.substr(start, found - start));
        out.append(to);
    }
    out.append(text.substr(start));
    return out;
}

} // namespace

std::filesystem::path local_path(std::string_view utf8) {
    return std::filesystem::path(std::u8string(utf8.begin(), utf8.end()));
}

std::string utf8_path(const std::filesystem::path& path) {
    const auto text = path.u8string();
    return std::string(text.begin(), text.end());
}

bool has_uri_scheme(std::string_view path) noexcept {
    const auto marker = path.find("://");
    if (marker == std::string_view::npos || marker == 0)
        return false;
    for (std::size_t i = 0; i < marker; ++i) {
        const char c = path[i];
        const bool alpha = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
        const bool other = (c >= '0' && c <= '9') || c == '+' || c == '-' || c == '.';
        if (!alpha && (i == 0 || !other))
            return false;
    }
    return true;
}

std::string_view without_query(std::string_view uri) noexcept {
    if (!has_uri_scheme(uri))
        return uri;
    return uri.substr(0, uri.find_first_of("?#"));
}

bool is_zip_name(std::string_view path) noexcept {
    const auto object = without_query(path);
    if (object.size() < 4)
        return false;
    auto suffix = std::string(object.substr(object.size() - 4));
    std::transform(suffix.begin(), suffix.end(), suffix.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return suffix == ".zip";
}

bool is_semver(std::string_view text) {
    static const std::regex pattern(
        R"(^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*))"
        R"((-[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$)");
    return std::regex_match(text.begin(), text.end(), pattern);
}

std::string trim_trailing_slashes(std::string_view path) {
    while (path.size() > 1 && is_separator(path.back()))
        path.remove_suffix(1);
    return std::string(path);
}

std::string child_path(std::string_view directory, std::string_view child) {
    return trim_trailing_slashes(directory) + "/" + std::string(child);
}

std::string parent_path(std::string_view path) {
    const std::string trimmed = trim_trailing_slashes(without_query(path));
    const auto slash = std::find_if(trimmed.rbegin(), trimmed.rend(), is_separator);
    if (slash == trimmed.rend())
        return ".";
    return trimmed.substr(0, static_cast<std::size_t>(trimmed.rend() - slash) - 1);
}

std::string source_name(std::string_view source) {
    const std::string trimmed = trim_trailing_slashes(without_query(source));
    const auto slash = std::find_if(trimmed.rbegin(), trimmed.rend(), is_separator);
    return slash == trimmed.rend() ? trimmed
                                   : trimmed.substr(static_cast<std::size_t>(trimmed.rend() - slash));
}

std::vector<std::string> source_labels(const std::vector<std::string>& sources) {
    std::vector<std::string> names;
    std::set<std::string> unique;
    for (const auto& source : sources) {
        names.push_back(source_name(source));
        unique.insert(names.back());
    }
    const bool usable = unique.size() == names.size() &&
                        std::none_of(names.begin(), names.end(),
                                     [](const std::string& name) { return name.empty(); });
    return usable ? names : sources;
}

std::string level_to_file(std::string_view level) {
    return replace_all(level, "/", "__") + std::string(parquet_suffix);
}

std::string file_to_level(std::string_view file_name) {
    return replace_all(file_name.substr(0, file_name.size() - parquet_suffix.size()), "__", "/");
}

std::string parent_level(std::string_view level) {
    if (level == "children")
        return "sample";
    const auto slash = level.rfind('/');
    return slash == std::string_view::npos ? "sample" : std::string(level.substr(0, slash));
}

std::string last_segment(std::string_view level) {
    const auto slash = level.rfind('/');
    return std::string(slash == std::string_view::npos ? level : level.substr(slash + 1));
}

std::uint64_t fnv1a64(std::string_view data, std::uint64_t hash) noexcept {
    for (const char c : data) {
        hash ^= static_cast<unsigned char>(c);
        hash *= 0x100000001B3ULL;
    }
    return hash;
}

std::string hex64(std::uint64_t value) {
    static constexpr char digits[] = "0123456789abcdef";
    std::string out(16, '0');
    for (int i = 15; i >= 0; --i, value >>= 4)
        out[static_cast<std::size_t>(i)] = digits[value & 0xF];
    return out;
}

std::string default_cache_dir() {
    if (auto configured = environment("TACO_CACHE_DIR"); !configured.empty())
        return configured;
#if defined(_WIN32)
    if (auto local = environment("LOCALAPPDATA"); !local.empty())
        return local + "\\taco\\cache";
#else
    if (auto xdg = environment("XDG_CACHE_HOME"); !xdg.empty())
        return xdg + "/taco";
    if (auto home = environment("HOME"); !home.empty())
        return home + "/.cache/taco";
#endif
    return ".taco-cache";
}

std::string sql_identifier(std::string_view name) {
    return "\"" + replace_all(name, "\"", "\"\"") + "\"";
}

std::string sql_literal(std::string_view value) {
    return "'" + replace_all(value, "'", "''") + "'";
}

} // namespace taco
