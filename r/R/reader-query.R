.check_idx <- function(idx) {
  if (is.null(idx)) {
    return(invisible(NULL))
  }
  if (!is.numeric(idx) || anyNA(idx) || !length(idx) %in% c(1L, 2L)) {
    .taco_stop("`idx` must be one sample number or a two-element range")
  }
  if (any(!is.finite(idx)) || any(idx != trunc(idx)) || any(idx < 0)) {
    .taco_stop("`idx` must contain whole, non-negative numbers")
  }
  if (any(idx > 2^53 - 1)) {
    .taco_stop("`idx` is too large to represent exactly in R")
  }
  if (length(idx) == 2L && idx[1L] > idx[2L]) {
    .taco_stop("`idx` range start must not exceed its end")
  }
  invisible(NULL)
}


.idx_text <- function(idx) {
  if (is.null(idx)) {
    return(NULL)
  }
  values <- format(idx, scientific = FALSE, trim = TRUE, digits = 22)
  if (length(values) == 1L) values else sprintf("[%s, %s]", values[1L], values[2L])
}


.check_names <- function(values, argument) {
  if (is.null(values)) {
    return(invisible(NULL))
  }
  if (!is.character(values) || anyNA(values) || !length(values)) {
    .taco_stop("`%s` must be a character vector with no NAs (or NULL)", argument)
  }
  if (any(!nzchar(values))) {
    .taco_stop("`%s` entries must be non-empty", argument)
  }
  invisible(NULL)
}


.read_table <- function(source, layout, idx, level, files, location) {
  .normalize_sources(source)
  layout <- match.arg(layout, c("wide", "long"))
  .check_idx(idx)
  .check_names(level, "level")
  if (!is.null(level) && length(level) != 1L) {
    .taco_stop("`level` must be a single level name")
  }
  .check_names(files, "files")
  if (!is.logical(location) || length(location) != 1L || is.na(location)) {
    .taco_stop("`location` must be TRUE or FALSE")
  }

  datasets <- lapply(source, function(path) .Call(taco_r_open, path))
  sql <- .Call(taco_r_sql, datasets, .idx_text(idx), level, layout == "wide", files, location)
  tibble::as_tibble(DBI::dbGetQuery(.open_reader(), sql))
}
