#pragma once

// Byte access through karu. Local paths, URIs and VSI paths all go through
// the same calls.

#include <cstdint>
#include <string>
#include <vector>

namespace taco {

struct Range {
    std::string uri;
    std::uint64_t offset = 0;
    std::uint64_t length = 0;
};

// karu's canonical form of a URI, such as /vsihf/ for hf://.
std::string canonical_uri(const std::string& uri);

std::uint64_t object_size(const std::string& uri);

// Reads every range in one karu batch, in request order.
std::vector<std::string> read_ranges(const std::vector<Range>& ranges);

// A whole object, refusing anything larger than limit bytes.
std::string read_object(const std::string& uri, std::uint64_t limit, const std::string& what);

// Stops the transport client cached by this thread.
void shutdown_transport() noexcept;

} // namespace taco
