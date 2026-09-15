.onLoad <- function(libname, pkgname) {
  reg.finalizer(.reader, function(environment) .shutdown_reader(), onexit = TRUE)
}


.onUnload <- function(libpath) {
  .shutdown_reader()
}
