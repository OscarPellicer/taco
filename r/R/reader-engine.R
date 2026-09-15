.taco_stop <- function(fmt, ...) {
  stop(sprintf(paste0("taco: ", fmt), ...), call. = FALSE)
}


.reader <- new.env(parent = emptyenv())
.reader$con <- NULL
.reader$shutdown <- FALSE


.open_reader <- function() {
  con <- .reader$con
  if (!is.null(con) && DBI::dbIsValid(con)) {
    return(con)
  }
  con <- DBI::dbConnect(duckdb::duckdb(shared_home = FALSE))
  .reader$con <- con
  con
}


.close_reader <- function() {
  con <- .reader$con
  if (!is.null(con) && DBI::dbIsValid(con)) {
    duckdb::dbDisconnect(con, shutdown = TRUE)
  }
  .reader$con <- NULL
  invisible(NULL)
}


.shutdown_reader <- function() {
  if (.reader$shutdown) {
    return(invisible(NULL))
  }
  .close_reader()
  .Call(taco_r_shutdown)
  .reader$shutdown <- TRUE
  invisible(NULL)
}
