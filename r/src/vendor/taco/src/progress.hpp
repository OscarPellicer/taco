#pragma once

// Progress of downloads and copies, in bytes. A phase starts with done 0 and
// ends when done reaches total. Bindings render it with their own bars; the
// built-in one writes to stderr when that is a terminal.

#include <taco/taco.h>

#include <cstdint>
#include <string>

namespace taco {

void set_progress(taco_progress_fn callback, void* user);
void report_progress(const std::string& phase, std::uint64_t done, std::uint64_t total);

} // namespace taco
