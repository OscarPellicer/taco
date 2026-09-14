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

# taco.reader forwards to the cozip DuckDB extension. Until it lands on the
# community registry, point at a local build of the sibling repository.
COZIP_EXTENSION ?= $(abspath ../cozip_reader/build/release/extension/cozip/cozip.duckdb_extension)
export COZIP_EXTENSION

.PHONY: python r julia javascript site clean

python:
	$(PYTHON) -m pip install -q "duckdb==$(DUCKDB_VERSION)" -e $(COZIP_PYTHON) -e "python[dev,test-eo]"
	$(PYTHON) -m ruff format --check --config python/pyproject.toml python/taco python/tests python/examples
	$(PYTHON) -m ruff check --config python/pyproject.toml python/taco python/tests python/examples docs/_build
	$(PYTHON) -m mypy --config-file python/pyproject.toml python/taco
	$(PYTHON) -m pytest python --cov=taco --cov-config=python/pyproject.toml --cov-report=term-missing
	rm -rf python/dist && cd python && (command -v uv >/dev/null && uv build -q || $(PYTHON) -m pip wheel -q --no-deps -w dist .) && ls dist

r:
	Rscript -e 'roxygen2::roxygenise("r")'
	Rscript -e 'testthat::test_local("r", reporter = "summary", stop_on_failure = TRUE)'

julia:
	cd julia && julia --project=. -e 'using Pkg; Pkg.test()'

javascript:
	cd javascript && npm ci && npm run types && npm test && npm pack --dry-run

site:
	$(PYTHON) docs/_build/build.py --output $(SITE) --clean

clean:
	rm -rf $(SITE) python/dist python/build python/*.egg-info .pytest_cache python/.pytest_cache \
	  .ruff_cache python/.ruff_cache .mypy_cache python/.mypy_cache numpy_demo.zip \
	  javascript/types javascript/node_modules javascript/*.tgz
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
