#' Read a TACO dataset
#'
#' `source` is one or more `.zip` archives, a FOLDER directory or a
#' `.tacocat` catalog, local or remote. Multiple sources must share a contract.
#'
#' @param source A dataset, or local paths or http(s)/s3/gcs/azure/hf URLs.
#' @param layout `"wide"` gives one row per sample with a column per
#'   structure leaf; `"long"` gives one row per file.
#' @param idx One sample number, or a two-element half-open range.
#'   `NULL` reads every sample.
#' @param level Return one contract level raw, with its internal columns,
#'   instead of the joined view.
#' @param files Restrict which structure leaves are read. `NULL` reads all.
#' @param location Fill structure columns in a wide read, or include the
#'   calculated `taco:location` column in a long read. Raw level reads never
#'   synthesize a location column.
#'
#' @return A tibble.
#' @export
read <- function(source, layout = c("wide", "long"), idx = NULL,
                 level = NULL, files = NULL, location = TRUE) {
  UseMethod("read")
}


#' @rdname read
#' @export
read.character <- function(source, layout = c("wide", "long"), idx = NULL,
                           level = NULL, files = NULL, location = TRUE) {
  resolution <- .resolve_dataset(source)
  sources <- resolution$sources
  if (length(sources) > 1L) {
    sources <- open_dataset(sources)[["sources"]]
  }
  .read_table(sources, layout, idx, level, files, location)
}


#' @rdname read
#' @export
read.taco_dataset <- function(source, layout = c("wide", "long"), idx = NULL,
                              level = NULL, files = NULL, location = TRUE) {
  .read_table(source[["sources"]], layout, idx, level, files, location)
}
