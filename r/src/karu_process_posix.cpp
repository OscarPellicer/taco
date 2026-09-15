#include "vendor/karu/src/process.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdint>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>

extern char** environ;

namespace karu::os {
namespace {

void wait_for_child(pid_t child, int& status) noexcept {
    while (::waitpid(child, &status, 0) < 0 && errno == EINTR) {
    }
}

void terminate_process(pid_t child, int& status) noexcept {
    ::kill(-child, SIGKILL);
    ::kill(child, SIGKILL);
    wait_for_child(child, status);
}

std::error_code setup_spawn(posix_spawn_file_actions_t& actions, posix_spawnattr_t& attributes,
                            int read_descriptor, int write_descriptor) {
    int status = posix_spawn_file_actions_init(&actions);
    if (status != 0)
        return {status, std::generic_category()};

    status = posix_spawnattr_init(&attributes);
    if (status != 0) {
        posix_spawn_file_actions_destroy(&actions);
        return {status, std::generic_category()};
    }

    const auto add_action = [&](int result) {
        if (status == 0 && result != 0)
            status = result;
    };
    add_action(posix_spawn_file_actions_adddup2(&actions, write_descriptor, STDOUT_FILENO));
    add_action(posix_spawn_file_actions_addclose(&actions, read_descriptor));
    if (write_descriptor != STDOUT_FILENO)
        add_action(posix_spawn_file_actions_addclose(&actions, write_descriptor));
    add_action(posix_spawnattr_setflags(&attributes, POSIX_SPAWN_SETPGROUP));
    add_action(posix_spawnattr_setpgroup(&attributes, 0));

    if (status != 0) {
        posix_spawnattr_destroy(&attributes);
        posix_spawn_file_actions_destroy(&actions);
        return {status, std::generic_category()};
    }
    return {};
}

} // namespace

std::expected<CommandResult, std::error_code>
run_command(std::string_view command, std::size_t output_limit, std::chrono::milliseconds timeout) {
    if (command.empty() || command.find('\0') != std::string_view::npos)
        return std::unexpected(std::make_error_code(std::errc::invalid_argument));

    const bool have_timeout = timeout > std::chrono::milliseconds::zero();
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    CommandResult result;
    std::string command_copy(command);

    int descriptors[2]{};
    if (::pipe(descriptors) != 0)
        return std::unexpected(std::error_code(errno, std::generic_category()));
    const int read_descriptor = descriptors[0];
    const int write_descriptor = descriptors[1];

    posix_spawn_file_actions_t actions;
    posix_spawnattr_t attributes;
    if (const std::error_code error =
            setup_spawn(actions, attributes, read_descriptor, write_descriptor)) {
        ::close(read_descriptor);
        ::close(write_descriptor);
        return std::unexpected(error);
    }

    std::array<char, 3> shell_name{'s', 'h', '\0'};
    std::array<char, 3> option{'-', 'c', '\0'};
    char* arguments[]{shell_name.data(), option.data(), command_copy.data(), nullptr};
    pid_t child = -1;
    const int spawn_status =
        posix_spawn(&child, "/bin/sh", &actions, &attributes, arguments, environ);
    posix_spawnattr_destroy(&attributes);
    posix_spawn_file_actions_destroy(&actions);
    ::close(write_descriptor);
    if (spawn_status != 0) {
        ::close(read_descriptor);
        return std::unexpected(std::error_code(spawn_status, std::generic_category()));
    }

    const int flags = ::fcntl(read_descriptor, F_GETFL, 0);
    if (flags < 0 || ::fcntl(read_descriptor, F_SETFL, flags | O_NONBLOCK) < 0) {
        const std::error_code error(errno, std::generic_category());
        int status = 0;
        terminate_process(child, status);
        ::close(read_descriptor);
        return std::unexpected(error);
    }

    int status = 0;
    bool pipe_closed = false;
    bool child_finished = false;
    while (!pipe_closed || !child_finished) {
        while (!pipe_closed) {
            std::array<char, 4096> buffer{};
            const ssize_t read = ::read(read_descriptor, buffer.data(), buffer.size());
            if (read > 0) {
                const std::size_t count = static_cast<std::size_t>(read);
                if (count > output_limit - std::min(output_limit, result.output.size())) {
                    result.output_limit_exceeded = true;
                    terminate_process(child, status);
                    ::close(read_descriptor);
                    return result;
                }
                result.output.append(buffer.data(), count);
                continue;
            }
            if (read == 0) {
                pipe_closed = true;
            } else if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) {
                const std::error_code error(errno, std::generic_category());
                terminate_process(child, status);
                ::close(read_descriptor);
                return std::unexpected(error);
            }
            break;
        }

        if (!child_finished) {
            const pid_t waited = ::waitpid(child, &status, WNOHANG);
            if (waited == child) {
                child_finished = true;
            } else if (waited < 0 && errno != EINTR) {
                const std::error_code error(errno, std::generic_category());
                ::kill(-child, SIGKILL);
                ::kill(child, SIGKILL);
                ::close(read_descriptor);
                return std::unexpected(error);
            }
        }
        if (have_timeout && std::chrono::steady_clock::now() >= deadline) {
            result.timed_out = true;
            if (!child_finished)
                terminate_process(child, status);
            else
                ::kill(-child, SIGKILL);
            ::close(read_descriptor);
            return result;
        }
        if (!pipe_closed || !child_finished) {
            const auto remaining = have_timeout
                                       ? std::chrono::duration_cast<std::chrono::milliseconds>(
                                             deadline - std::chrono::steady_clock::now())
                                       : std::chrono::milliseconds(50);
            const int wait_ms =
                static_cast<int>(std::clamp<std::int64_t>(remaining.count(), 1, 50));
            pollfd descriptor{read_descriptor, POLLIN | POLLHUP, 0};
            ::poll(&descriptor, 1, wait_ms);
        }
    }

    ::close(read_descriptor);
    if (WIFEXITED(status))
        result.exit_code = WEXITSTATUS(status);
    else if (WIFSIGNALED(status))
        result.exit_code = 128 + WTERMSIG(status);
    return result;
}

} // namespace karu::os
