.onLoad <- function(libname, pkgname) {
  .Call(taco_r_set_progress, .progress_handler)
  reg.finalizer(.reader, function(environment) .shutdown_reader(), onexit = TRUE)
}


.onUnload <- function(libpath) {
  .Call(taco_r_set_progress, NULL)
  .shutdown_reader()
}
