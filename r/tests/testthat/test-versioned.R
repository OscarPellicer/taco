.fixture_collection <- function() {
  folder <- tempfile("taco-collection-")
  dir.create(folder)
  on.exit(unlink(folder, recursive = TRUE), add = TRUE)
  utils::unzip(taco_fixture(), files = "COLLECTION.json", exdir = folder)
  jsonlite::read_json(
    file.path(folder, "COLLECTION.json"),
    simplifyVector = FALSE
  )
}


.versioned_manifest <- function() {
  first <- .fixture_collection()
  second <- first
  second$dataset_version <- "2.0.0"
  list(
    "taco:container" = "versioned",
    "taco:default_version" = "2.0.0",
    "taco:versions" = list(
      "1.0.0" = list(href = "1.0.0/", collection = first),
      "2.0.0" = list(href = "2.0.0/", collection = second)
    )
  )
}


.write_manifest <- function(root, manifest = .versioned_manifest()) {
  dir.create(root)
  path <- file.path(root, "taco.json")
  jsonlite::write_json(manifest, path, auto_unbox = TRUE, pretty = TRUE)
  path
}


describe("versioned dataset discovery", {
  it("opens a local root from one manifest read", {
    root <- tempfile("taco-versioned-")
    on.exit(unlink(root, recursive = TRUE), add = TRUE)
    manifest_path <- .write_manifest(root)

    dataset <- taco::open_dataset(root)

    expect_s3_class(dataset, "taco_dataset")
    expect_identical(dataset$sources, normalizePath(file.path(root, "2.0.0"), mustWork = FALSE))
    expect_identical(dataset$collection$dataset_version, "2.0.0")
    expect_identical(dataset$version, "2.0.0")
    expect_identical(dataset$versions, c("1.0.0", "2.0.0"))
    expect_identical(dataset$manifest, manifest_path)
  })

  it("accepts an explicit taco.json path", {
    root <- tempfile("taco-versioned-")
    on.exit(unlink(root, recursive = TRUE), add = TRUE)
    path <- .write_manifest(root)

    dataset <- taco::open_dataset(path)

    expect_identical(dataset$version, "2.0.0")
    expect_identical(dataset$manifest, path)
  })

  it("resolves read calls to the default version", {
    root <- tempfile("taco-versioned-")
    version <- file.path(root, "2.0.0")
    on.exit(unlink(root, recursive = TRUE), add = TRUE)
    .write_manifest(root)
    dir.create(version)
    utils::unzip(taco_fixture(), exdir = version)

    result <- taco::read(root, idx = 0)

    expect_identical(nrow(result), 1L)
  })

  it("does not probe explicit containers or version directories", {
    expect_null(taco:::.manifest_candidate("https://example.test/part.zip"))
    expect_null(taco:::.manifest_candidate("https://example.test/PART.ZIP"))
    expect_null(taco:::.manifest_candidate("https://example.test/.tacocat/"))
    expect_null(taco:::.manifest_candidate("https://example.test/data/1.2.3/"))
    expect_identical(
      taco:::.manifest_candidate("https://example.test/data.v3/"),
      "https://example.test/data.v3/taco.json"
    )
  })

  it("preserves absolute version hrefs", {
    root <- tempfile("taco-versioned-")
    on.exit(unlink(root, recursive = TRUE), add = TRUE)
    manifest <- .versioned_manifest()
    manifest[["taco:versions"]][["2.0.0"]]$href <- "https://cdn.example/dataset.zip"
    .write_manifest(root, manifest)

    dataset <- taco::open_dataset(root)

    expect_identical(dataset$sources, "https://cdn.example/dataset.zip")
  })

  it("resolves remote href forms", {
    candidate <- "https://example.test/catalog/releases/taco.json"
    expect_identical(
      taco:::.join_manifest_href(candidate, "../2.0.0/"),
      "https://example.test/catalog/2.0.0/"
    )
    expect_identical(
      taco:::.join_manifest_href(candidate, "/stable/data.zip"),
      "https://example.test/stable/data.zip"
    )
    expect_identical(
      taco:::.join_manifest_href(candidate, "//cdn.example/data.zip"),
      "https://cdn.example/data.zip"
    )
  })

  it("rejects invalid manifests", {
    cases <- list(
      list(change = function(x) { x[["taco:container"]] <- "zip"; x }, message = "taco:container"),
      list(change = function(x) { x[["taco:versions"]] <- list(); x }, message = "at least one"),
      list(change = function(x) { x[["taco:default_version"]] <- "3.0.0"; x }, message = "not present"),
      list(change = function(x) {
        x[["taco:versions"]][["latest"]] <- x[["taco:versions"]][["1.0.0"]]
        x[["taco:versions"]][["1.0.0"]] <- NULL
        x
      }, message = "Semantic Versioning"),
      list(change = function(x) { x[["taco:versions"]][["1.0.0"]]$href <- ""; x }, message = "non-empty href"),
      list(change = function(x) {
        x[["taco:versions"]][["2.0.0"]]$collection$dataset_version <- "1.0.0"
        x
      }, message = "embeds collection dataset_version"),
      list(change = function(x) {
        x[["taco:versions"]][["2.0.0"]]$collection$description <- NULL
        x
      }, message = "invalid collection")
    )

    for (case in cases) {
      root <- tempfile("taco-versioned-")
      manifest <- case$change(.versioned_manifest())
      path <- .write_manifest(root, manifest)
      expect_error(taco::open_dataset(path), case$message)
      unlink(root, recursive = TRUE)
    }
  })

  it("rejects invalid JSON and a missing explicit manifest", {
    root <- tempfile("taco-versioned-")
    dir.create(root)
    on.exit(unlink(root, recursive = TRUE), add = TRUE)
    path <- file.path(root, "taco.json")
    writeLines("not JSON", path)
    expect_error(taco::open_dataset(path), "not valid JSON")
    unlink(path)
    expect_error(taco::open_dataset(path), "does not exist")
  })
})
