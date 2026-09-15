#pragma once

// Versioned dataset roots: a taco.json that lists releases and names the
// default one.

#include <optional>
#include <string>

namespace taco {

// Where a manifest would be for source, or nothing for a ZIP, a TACOCAT, a
// version directory or a local directory without taco.json.
std::optional<std::string> manifest_candidate(const std::string& source);

// href as listed by the manifest at candidate. A local result is joined but
// not normalized, so each binding keeps its own path conventions.
std::string join_manifest_href(const std::string& candidate, const std::string& href);

// A JSON object with source, collection, version, versions and manifest.
std::string resolve_dataset(const std::string& source);

} // namespace taco
