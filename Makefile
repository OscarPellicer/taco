# make core      build and test the native reader shared by Python, R and Julia
# make sync-r-core refresh the native sources carried by the R source package
# make python    install taco, lint, test and build the wheel
# make r         check the R reader
# make julia     check the Julia reader
# make javascript check and package the JavaScript reader
# make site      compile docs/ into _site/ (what GitHub Pages deploys)
# make clean     remove build output and caches

PYTHON ?= python
SITE   := _site
DUCKDB_VERSION ?= 1.5.5
COZIP_PYTHON ?= ../cozip/python
BUILD_TYPE ?= Release
OPENSSL_ROOT_DIR ?= $(shell brew --prefix openssl@3 2>/dev/null)

CORE_BUILD := core/build
CORE_LIB := $(CORE_BUILD)/$(if $(filter Darwin,$(shell uname -s)),libtaco.dylib,libtaco.so)

# Julia links the development core built here. R compiles its vendored copy.
export TACO_CORE_DIR := $(abspath core)
export TACO_LIB := $(abspath $(CORE_LIB))

.PHONY: core sync-r-core python r julia javascript site clean

core:
	cmake -S core -B $(CORE_BUILD) -DCMAKE_BUILD_TYPE=$(BUILD_TYPE) -DTACO_BUILD_TESTS=ON \
	  $(if $(OPENSSL_ROOT_DIR),-DOPENSSL_ROOT_DIR=$(OPENSSL_ROOT_DIR))
	cmake --build $(CORE_BUILD) --parallel
	ctest --test-dir $(CORE_BUILD) --output-on-failure
	mkdir -p python/taco/_lib && cp $(CORE_LIB) python/taco/_lib/

sync-r-core:
	$(PYTHON) tools/sync_r_core.py

python: core
	$(PYTHON) -m pip install -q "duckdb==$(DUCKDB_VERSION)" -e $(COZIP_PYTHON) -e "python[dev,test-eo]"
	$(PYTHON) -m ruff format --check --config python/pyproject.toml python/taco python/tests python/examples
	$(PYTHON) -m ruff check --config python/pyproject.toml python/taco python/tests python/examples docs/_build
	$(PYTHON) -m mypy --config-file python/pyproject.toml python/taco
	$(PYTHON) -m pytest python --cov=taco --cov-config=python/pyproject.toml --cov-report=term-missing
	rm -rf python/dist && cd python && (command -v uv >/dev/null && uv build -q || $(PYTHON) -m pip wheel -q --no-deps -w dist .) && ls dist

r: sync-r-core
	Rscript -e 'roxygen2::roxygenise("r")'
	Rscript -e 'testthat::test_local("r", reporter = "summary", stop_on_failure = TRUE)'

julia: core
	cd julia && julia --project=. -e 'using Pkg; Pkg.test()'

javascript:
	cd javascript && npm ci && npm run types && npm test && npm pack --dry-run

site:
	$(PYTHON) docs/_build/build.py --output $(SITE) --clean

clean:
	rm -rf $(SITE) $(CORE_BUILD) python/taco/_lib r/src/*.o r/src/*.so \
	  python/dist python/build python/*.egg-info .pytest_cache python/.pytest_cache \
	  .ruff_cache python/.ruff_cache .mypy_cache python/.mypy_cache numpy_demo.zip \
	  javascript/types javascript/node_modules javascript/*.tgz
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
