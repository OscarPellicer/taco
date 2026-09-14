#' @export
print.taco_dataset <- function(x, ...) {
  collection <- x[["collection"]]
  count <- length(x[["sources"]])
  cat(sprintf(
    "taco.Dataset(%s, version=%s, sources=%d)\n",
    collection[["id"]], collection[["dataset_version"]], count
  ))
  invisible(x)
}
