.is_url <- function(source) {
  grepl("^[A-Za-z][A-Za-z0-9+.-]*://", source)
}


.local_path <- function(path) {
  if (.is_url(path)) path else normalizePath(path, mustWork = FALSE)
}


.manifest_candidate <- function(source) {
  .Call(taco_r_manifest_candidate, source)
}


.join_manifest_href <- function(candidate, href) {
  .local_path(.Call(taco_r_join_manifest_href, candidate, href))
}


.resolve_dataset <- function(source) {
  sources <- .normalize_sources(source)
  direct <- list(
    sources = sources,
    collection = NULL,
    version = NULL,
    versions = character(),
    manifest = NULL
  )
  if (length(sources) != 1L) {
    return(direct)
  }

  resolution <- jsonlite::fromJSON(.Call(taco_r_resolve, sources), simplifyVector = FALSE)
  if (is.null(resolution$manifest)) {
    return(direct)
  }
  list(
    sources = .local_path(resolution$source),
    collection = resolution$collection,
    version = resolution$version,
    versions = as.character(unlist(resolution$versions)),
    manifest = .local_path(resolution$manifest)
  )
}
