# Releasing TACO

TACO has two independent package versions:

- the native core and the Python, R, and Julia bindings share one version;
- `@asterisk-labs/taco` has its own npm version.

Keep the native version synchronized in `core/CMakeLists.txt`,
`core/vcpkg.json`, `python/pyproject.toml`, `r/DESCRIPTION`, `r/configure.ac`,
and `julia/Project.toml`. Keep the JavaScript version synchronized only between
`javascript/package.json` and `javascript/package-lock.json`.
Move the pending entries in the root `CHANGELOG.md` under the version being
released before creating either tag.

## Native and package tags

Julia needs checksums for the native archives in the source tree. Releases
therefore use two tags:

1. Tag the reviewed commit as `libtaco-vX.Y.Z`. The release workflow builds
   and publishes the five native archives, then updates `julia/Artifacts.toml`
   on `main`.
2. Review that generated commit and tag it as `vX.Y.Z`. The workflow refuses
   this tag unless all five artifact entries point at `libtaco-vX.Y.Z`.

The final tag tests the installed Julia package without `TACO_LIB` before it
publishes Python or npm packages. This guarantees that installing the final
tag can resolve the native library on every supported platform.

Run the release workflow manually before tagging when a full packaging dry
run is useful. A manual run builds and tests packages but publishes nothing.
