.progress <- new.env(parent = emptyenv())
.progress$bars <- list()


# Native download progress, grouped by phase. cli stays quiet outside a terminal.
.progress_handler <- function(phase, done, total) {
  id <- .progress$bars[[phase]]
  if (is.null(id)) {
    id <- cli::cli_progress_bar(
      phase,
      total = if (total > 0) total else NA,
      type = "download",
      .auto_close = FALSE,
      .envir = .progress
    )
    .progress$bars[[phase]] <- id
  }
  cli::cli_progress_update(set = done, id = id, .envir = .progress)
  if (total > 0 && done >= total) {
    cli::cli_progress_done(id = id, .envir = .progress)
    .progress$bars[[phase]] <- NULL
  }
  invisible(NULL)
}
