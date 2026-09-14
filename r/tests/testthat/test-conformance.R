test_that("reader URL resolution follows the shared conformance cases", {
  path <- system.file("conformance", "reader-resolution.json", package = "taco")
  expect_true(nzchar(path))
  cases <- jsonlite::fromJSON(path, simplifyVector = FALSE)

  for (case in cases$manifest_candidates) {
    expect_identical(taco:::.manifest_candidate(case$source), case$expected)
  }
  for (case in cases$manifest_hrefs) {
    expect_identical(
      taco:::.join_manifest_href(case$candidate, case$href),
      case$expected
    )
  }
})
