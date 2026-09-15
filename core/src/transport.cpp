#include "transport.hpp"

#include "error.hpp"
#include "paths.hpp"

#include <karu/karu.h>

#include <memory>

namespace taco {
namespace {

// Each thread reuses its connection pool while the transport configuration in
// the environment stays the same. A change is noticed on the next call.
thread_local std::shared_ptr<karu_client> cached_client;

struct LocatorDeleter {
    void operator()(karu_locator* locator) const noexcept { karu_locator_free(locator); }
};

struct ConfigDeleter {
    void operator()(karu_config* config) const noexcept { karu_config_free(config); }
};

using Locator = std::unique_ptr<karu_locator, LocatorDeleter>;

[[noreturn]] void transport_error(karu_status status, const std::string& action) {
    const char* detail = karu_last_error();
    std::string message = action + ": " + (detail && *detail ? detail : karu_status_string(status));
    switch (status) {
    case KARU_ERR_NOT_FOUND:
        throw Error(TACO_ERR_NOT_FOUND, message, status);
    case KARU_ERR_URI:
    case KARU_ERR_INVALID:
    case KARU_ERR_UNSUPPORTED:
        throw Error(TACO_ERR_INVALID, message, status);
    default:
        throw Error(TACO_ERR_IO, message, status);
    }
}

std::shared_ptr<karu_client> client() {
    karu_config* raw_config = nullptr;
    karu_status status = karu_config_create(&raw_config);
    if (status != KARU_OK)
        transport_error(status, "could not read the transport configuration");
    const std::unique_ptr<karu_config, ConfigDeleter> config(raw_config);

    if (cached_client) {
        int matches = 0;
        status = karu_client_matches_config(cached_client.get(), config.get(), &matches);
        if (status != KARU_OK)
            transport_error(status, "could not compare the transport configuration");
        if (matches)
            return cached_client;
    }

    karu_client* created = nullptr;
    status = karu_client_create(config.get(), &created);
    if (status != KARU_OK)
        transport_error(status, "could not create the transport");
    cached_client = std::shared_ptr<karu_client>(created, karu_client_free);
    return cached_client;
}

Locator resolve(const std::string& uri) {
    karu_locator* raw = nullptr;
    const karu_status status = karu_resolve(uri.c_str(), &raw);
    if (status != KARU_OK)
        transport_error(status, "could not resolve " + redact_uri(uri));
    return Locator(raw);
}

} // namespace

std::string canonical_uri(const std::string& uri) {
    return karu_locator_uri(resolve(uri).get());
}

std::uint64_t object_size(const std::string& uri) {
    const auto transport = client();
    const Locator locator = resolve(uri);
    std::uint64_t size = 0;
    const karu_status status = karu_client_size(transport.get(), locator.get(), &size);
    if (status != KARU_OK)
        transport_error(status, "could not open " + redact_uri(uri));
    return size;
}

std::vector<std::string> read_ranges(const std::vector<Range>& ranges) {
    std::vector<std::string> buffers(ranges.size());
    std::vector<Locator> locators;
    std::vector<karu_req> requests;
    for (std::size_t i = 0; i < ranges.size(); ++i) {
        if (ranges[i].length == 0)
            continue;
        locators.push_back(resolve(ranges[i].uri));
        buffers[i].resize(ranges[i].length);
        requests.push_back(karu_req{.locator = locators.back().get(),
                                    .offset = ranges[i].offset,
                                    .length = ranges[i].length,
                                    .buffer = buffers[i].data(),
                                    .tag = nullptr,
                                    .if_match = nullptr});
    }
    if (requests.empty())
        return buffers;
    const auto transport = client();
    const karu_status status = karu_client_fetch(transport.get(), requests.data(), requests.size());
    if (status != KARU_OK)
        transport_error(status, "could not read " + redact_uri(ranges.front().uri));
    return buffers;
}

std::string read_object(const std::string& uri, std::uint64_t limit, const std::string& what) {
    const std::uint64_t size = object_size(uri);
    if (size > limit)
        fail(what + " is larger than " + std::to_string(limit / (1024 * 1024)) +
             " MiB, refusing to read it: " + redact_uri(uri));
    return std::move(read_ranges({Range{uri, 0, size}}).front());
}

} // namespace taco
