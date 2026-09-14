.normalize_sources <- function(source) {
  if (!is.character(source) || !length(source) || anyNA(source) ||
      any(!nzchar(source))) {
    .taco_stop("`source` must contain one or more non-empty strings")
  }
  if (anyDuplicated(source)) {
    .taco_stop("`source` paths must be unique")
  }
  source
}


.source_labels <- function(sources) {
  labels <- basename(sub("/+$", "", sources))
  if (all(nzchar(labels)) && !anyDuplicated(labels)) labels else sources
}
