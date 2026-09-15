#pragma once

#include <taco/taco.h>

#include <stdexcept>
#include <string>

namespace taco {

class Error : public std::runtime_error {
  public:
    // transport carries the karu status of a failed read, or 0.
    Error(taco_status status, const std::string& message, int transport = 0)
        : std::runtime_error(message), status_(status), transport_(transport) {}

    [[nodiscard]] taco_status status() const noexcept { return status_; }
    [[nodiscard]] int transport() const noexcept { return transport_; }

  private:
    taco_status status_;
    int transport_;
};

[[noreturn]] inline void fail(const std::string& message) {
    throw Error(TACO_ERR_INVALID, message);
}

} // namespace taco
