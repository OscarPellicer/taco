.SEMVER <- paste0(
  "^(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)\\.(?:0|[1-9][0-9]*)",
  "(?:-[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?",
  "(?:\\+[0-9A-Za-z-]+(?:\\.[0-9A-Za-z-]+)*)?$"
)


.source_name <- function(source) {
  path <- sub("[?#].*$", "", sub("/+$", "", source))
  basename(path)
}


.direct_source <- function(source) {
  name <- .source_name(source)
  identical(name, ".tacocat") ||
    grepl("\\.zip$", name, ignore.case = TRUE) ||
    grepl(.SEMVER, name, perl = TRUE)
}


.is_url <- function(source) {
  grepl("^[A-Za-z][A-Za-z0-9+.-]*://", source)
}


.manifest_candidate <- function(source) {
  if (identical(.source_name(source), "taco.json")) {
    return(source)
  }
  if (.direct_source(source)) {
    return(NULL)
  }
  if (.is_url(source)) {
    clean <- sub("[?#].*$", "", source)
    return(paste0(sub("/+$", "", clean), "/taco.json"))
  }
  candidate <- file.path(source, "taco.json")
  if (file.exists(candidate)) candidate else NULL
}


.read_manifest <- function(candidate, required) {
  if (!.is_url(candidate)) {
    if (!file.exists(candidate)) {
      if (!required) return(NULL)
      .taco_stop("versioned manifest does not exist: %s", candidate)
    }
    return(tryCatch(
      readBin(candidate, what = "raw", n = file.info(candidate)$size),
      error = function(err) {
        .taco_stop("could not read versioned manifest %s: %s", candidate, conditionMessage(err))
      }
    ))
  }

  response <- tryCatch(
    curl::curl_fetch_memory(
      candidate,
      handle = curl::new_handle(followlocation = TRUE)
    ),
    error = function(err) {
      .taco_stop("could not read versioned manifest %s: %s", candidate, conditionMessage(err))
    }
  )
  if (identical(response$status_code, 404L) && !required) {
    return(NULL)
  }
  if (response$status_code < 200L || response$status_code >= 300L) {
    .taco_stop(
      "could not read versioned manifest %s: HTTP %d",
      candidate,
      response$status_code
    )
  }
  response$content
}


.json_object <- function(value, context) {
  if (!is.list(value) || (length(value) && (is.null(names(value)) || any(!nzchar(names(value)))))) {
    .taco_stop("%s must be an object", context)
  }
  value
}


.parse_manifest <- function(payload, candidate) {
  manifest <- tryCatch(
    jsonlite::fromJSON(rawToChar(payload), simplifyVector = FALSE),
    error = function(err) {
      .taco_stop("versioned manifest is not valid JSON: %s", candidate)
    }
  )
  manifest <- .json_object(manifest, "versioned manifest")
  if (!identical(manifest[["taco:container"]], "versioned")) {
    .taco_stop("taco:container must be 'versioned'")
  }
  manifest
}


.normalize_url_path <- function(path) {
  trailing <- endsWith(path, "/")
  result <- character()
  for (segment in strsplit(path, "/", fixed = TRUE)[[1L]]) {
    if (!nzchar(segment) || identical(segment, ".")) next
    if (identical(segment, "..")) {
      if (length(result)) result <- result[-length(result)]
    } else {
      result <- c(result, segment)
    }
  }
  normalized <- paste0("/", paste(result, collapse = "/"))
  if (trailing && normalized != "/") normalized <- paste0(normalized, "/")
  normalized
}


.join_manifest_href <- function(candidate, href) {
  if (.is_url(href)) {
    return(href)
  }
  if (!.is_url(candidate)) {
    if (grepl("^[/\\\\]", href)) {
      return(normalizePath(sub("[/\\\\]+$", "", href), mustWork = FALSE))
    }
    joined <- file.path(dirname(candidate), href)
    return(normalizePath(sub("[/\\\\]+$", "", joined), mustWork = FALSE))
  }

  clean <- sub("[?#].*$", "", candidate)
  if (startsWith(href, "//")) {
    scheme <- sub("^([A-Za-z][A-Za-z0-9+.-]*):.*$", "\\1", clean)
    return(paste0(scheme, ":", href))
  }
  if (startsWith(href, "/")) {
    origin <- sub("^([A-Za-z][A-Za-z0-9+.-]*://[^/]+).*$", "\\1", clean)
    return(paste0(origin, .normalize_url_path(href)))
  }
  origin <- sub("^([A-Za-z][A-Za-z0-9+.-]*://[^/]+).*$", "\\1", clean)
  candidate_path <- sub("^[A-Za-z][A-Za-z0-9+.-]*://[^/]+", "", clean)
  if (!nzchar(candidate_path)) candidate_path <- "/"
  target <- paste0(sub("[^/]*$", "", candidate_path), href)
  paste0(origin, .normalize_url_path(target))
}


.validate_embedded_collection <- function(collection, version) {
  required <- c(
    "taco:version", "id", "dataset_version", "description", "licenses",
    "providers", "tasks", "taco:structure", "taco:metadata"
  )
  missing <- setdiff(required, names(collection))
  if (length(missing)) {
    .taco_stop(
      "version '%s' embeds an invalid collection: missing required fields %s",
      version,
      paste(missing, collapse = ", ")
    )
  }
  if (!identical(collection[["taco:version"]], "3.0.0")) {
    .taco_stop("version '%s' embeds an invalid collection: taco:version must be 3.0.0", version)
  }
  if (!is.list(collection[["taco:metadata"]])) {
    .taco_stop("version '%s' embeds an invalid collection: taco:metadata must be an object", version)
  }
  invisible(collection)
}


.resolve_versioned <- function(source) {
  sources <- .check_source(source)
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

  original <- sources[[1L]]
  explicit <- identical(.source_name(original), "taco.json")
  candidate <- .manifest_candidate(original)
  if (is.null(candidate)) {
    return(direct)
  }
  payload <- .read_manifest(candidate, required = explicit)
  if (is.null(payload)) {
    return(direct)
  }

  manifest <- .parse_manifest(payload, candidate)
  versions <- .json_object(manifest[["taco:versions"]], "taco:versions")
  if (!length(versions)) {
    .taco_stop("taco:versions must contain at least one version")
  }
  selected <- manifest[["taco:default_version"]]
  if (!is.character(selected) || length(selected) != 1L || !nzchar(selected)) {
    .taco_stop("taco:default_version must be a non-empty string")
  }
  if (!selected %in% names(versions)) {
    .taco_stop("taco:default_version '%s' is not present in taco:versions", selected)
  }

  entries <- vector("list", length(versions))
  names(entries) <- names(versions)
  for (version in names(versions)) {
    if (!grepl(.SEMVER, version, perl = TRUE)) {
      .taco_stop("taco:versions key '%s' must follow Semantic Versioning", version)
    }
    entry <- .json_object(versions[[version]], sprintf("version '%s'", version))
    href <- entry[["href"]]
    if (!is.character(href) || length(href) != 1L || !nzchar(href)) {
      .taco_stop("version '%s' needs a non-empty href", version)
    }
    collection <- .json_object(
      entry[["collection"]],
      sprintf("version '%s' collection", version)
    )
    if (!identical(collection[["dataset_version"]], version)) {
      embedded_version <- collection[["dataset_version"]]
      if (is.null(embedded_version)) embedded_version <- "<missing>"
      .taco_stop(
        "version '%s' embeds collection dataset_version '%s'",
        version,
        as.character(embedded_version)
      )
    }
    entries[[version]] <- list(href = href, collection = collection)
  }

  selected_entry <- entries[[selected]]
  .validate_embedded_collection(selected_entry$collection, selected)
  list(
    sources = .join_manifest_href(candidate, selected_entry$href),
    collection = selected_entry$collection,
    version = selected,
    versions = names(versions),
    manifest = candidate
  )
}
