#pragma once

#include <optional>
#include <string_view>

namespace taco {

// Consume a band or time index, rejecting leading zeros.
inline bool consume_rumi_index(std::string_view& rest, char axis) {
    if (rest.size() < 2 || rest.front() != axis)
        return false;
    std::size_t end = 1;
    while (end < rest.size() && rest[end] >= '0' && rest[end] <= '9')
        ++end;
    if (end == 1 || (rest[1] == '0' && end > 2))
        return false;
    rest.remove_prefix(end);
    return true;
}

// Accept a statistic name, optionally scoped to a band, time step, or both.
inline bool is_rumi_statistic(std::string_view name) {
    for (const std::string_view kind : {"minimum", "maximum", "mean", "stddev", "p2", "p98"}) {
        if (!name.starts_with(kind))
            continue;
        auto rest = name.substr(kind.size());
        if (rest.empty())
            return true;
        if (rest.front() != '_')
            return false;
        rest.remove_prefix(1);
        if (consume_rumi_index(rest, 't')) {
            if (rest.empty())
                return true;
            if (rest.front() != '_')
                return false;
            rest.remove_prefix(1);
        }
        return consume_rumi_index(rest, 'b') && rest.empty();
    }
    return false;
}

// The generated-column suffix of a valid Rumi field, or nothing.
inline std::optional<std::string_view> rumi_file_suffix(std::string_view field) {
    constexpr std::string_view prefix = "rumi:";
    if (!field.starts_with(prefix))
        return std::nullopt;
    const auto name = field.substr(prefix.size());
    if (name == "header" || is_rumi_statistic(name))
        return name;
    return std::nullopt;
}

} // namespace taco
