# Convenience wrappers. Everything here is `uv` underneath; run the uv commands
# directly if you prefer.
#
# `--directory daemon` on every one of them: the Python project is `daemon/`,
# beside `client/` and `proto/`, so that this repository has the shape every
# braemons daemon repository has (contracts/DAEMON_LAYOUT.md). The alternative
# was a pyproject.toml at the root claiming the whole tree is one package, which
# it is not.

.PHONY: help sync test lint fmt typecheck check sim clean version \
        proto check-proto deb wheel packages package-check

help:
	@echo "make sync       install the dev environment"
	@echo "make test       run the test suite"
	@echo "make lint       ruff check + format --check"
	@echo "make fmt        ruff format"
	@echo "make typecheck  ty check"
	@echo "make check      lint + typecheck + test + the proto + a simulated session"
	@echo "make proto      regenerate what proto/ derives from other files"
	@echo "make check-proto  the proto compiles, is current, and matches the router"
	@echo "make sim        run a simulated session"
	@echo "make version    the version the git tag implies"
	@echo ""
	@echo "Packaging (packaging/Makefile has the rest, and the reasons):"
	@echo "make deb        the .deb for this machine"
	@echo "make wheel      the wheel and the sdist"
	@echo "make packages   every artifact a release publishes, in the pinned image"
	@echo "make package-check  stage the tree and run it, packaging nothing"

sync:
	uv sync --directory daemon --extra serve --group dev

test:
	uv run --directory daemon pytest

lint:
	uv run --directory daemon ruff check .
	uv run --directory daemon ruff format --check .

fmt:
	uv run --directory daemon ruff format .

typecheck:
	uv run --directory daemon ty check

# `proto/triald/v1/` is this daemon's public API — types and behaviours both
# (contracts/DAEMON_LAYOUT.md). Most of it is authored by hand; outcomes.proto
# is not, because the outcome taxonomy belongs to the family rather than to this
# daemon and its authored copy is the vendored outcomes.json.
proto: ## regenerate what proto/ derives from other files
	python3 tools/generate_outcomes_proto.py

# Three checks, catching three different mistakes: protoc catches a file that
# does not parse; --check catches a derived file left behind by a change to the
# taxonomy; and check_routes.py catches a handler decorated into the router with
# no rpc above it — public API that exists and is written down nowhere.
#
# --check rather than regenerate-then-`git diff`: the git version is vacuous for
# a file that is not tracked yet, which is exactly when a new generator has
# earned the least trust.
check-proto: ## the proto compiles, is current, and matches the router
	@protoc --proto_path=proto --descriptor_set_out=/dev/null \
	  proto/triald/v1/*.proto proto/braemons/v1/route.proto
	@python3 tools/generate_outcomes_proto.py --check
	@python3 tools/check_routes.py

# What CI runs. The simulated session is the end-to-end smoke test.
check: lint typecheck test check-proto
	uv run --directory daemon triald sim --trials 200
	uv run --directory daemon triald policy check ../examples/staircase.py --trial-types contrast_0,contrast_1,contrast_2,contrast_3,contrast_4,contrast_5

sim:
	uv run --directory daemon triald sim --trials 200 --trace

version:
	@sh packaging/scripts/git-version.sh

# Thin wrappers. The reasons live in packaging/Makefile, which is where the
# recipes are; these exist so that `make deb` from the root does the obvious
# thing rather than nothing.
deb:
	$(MAKE) -C packaging deb

wheel:
	$(MAKE) -C packaging wheel

packages:
	$(MAKE) -C packaging packages

package-check:
	$(MAKE) -C packaging check

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov dist build
