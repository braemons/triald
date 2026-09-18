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
	@echo "make proto      regenerate daemon/src/triald/_proto/ from proto/"
	@echo "make check-proto  the proto compiles, is current, and matches the taxonomy and routes"
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
# (contracts/DAEMON_LAYOUT.md). All of it is authored by hand, including the
# outcome taxonomy: it used to be a JSON file with vendored copies and a regex
# checker, and a protobuf enum is the thing that file was imitating.
#
# Three checks, catching three different mistakes: protoc catches a file that
# does not parse; check_outcomes.py catches a copy of the taxonomy that drifted
# from the enum; and check_routes.py catches a handler decorated into the router
# with no rpc above it — public API that exists and is written down nowhere.
# The generated code is committed, so a checkout runs without protoc and an
# interface change arrives as a diff a reviewer can read
# (contracts/DAEMON_LAYOUT.md).
#
# service.proto is not generated, and that is not an oversight: it declares
# behaviour, this family runs no gRPC, and protobuf's Python output for a
# service is a descriptor with no stubs. Generating it would only drag
# braemons/v1/route.proto into the runtime import path for nothing.
proto: ## regenerate daemon/src/triald/_proto/ from proto/
	@protoc --proto_path=proto --python_out=daemon/src/triald/_proto $(MESSAGE_PROTOS)
	@echo "daemon/src/triald/_proto/"

MESSAGE_PROTOS := $(filter-out proto/triald/v1/service.proto,$(wildcard proto/triald/v1/*.proto))

check-proto: ## the proto compiles, is current, and matches the taxonomy and routes
	@protoc --proto_path=proto --descriptor_set_out=/dev/null \
	  proto/triald/v1/*.proto proto/braemons/v1/route.proto
	@# Into a scratch directory and compared, rather than regenerated in place
	@# and handed to `git diff`: the git version is vacuous for a file git does
	@# not track yet, which is exactly when a new generator is least trusted.
	@rm -rf build/proto-check && mkdir -p build/proto-check
	@protoc --proto_path=proto --python_out=build/proto-check $(MESSAGE_PROTOS)
	@diff -r -x '__pycache__' build/proto-check daemon/src/triald/_proto >/dev/null || { \
	  echo "daemon/src/triald/_proto/ is not what proto/ produces — the interface changed:"; \
	  diff -rq -x '__pycache__' build/proto-check daemon/src/triald/_proto || true; \
	  echo "run 'make proto' and commit the result with the change that caused it."; \
	  exit 1; \
	}
	@rm -rf build/proto-check
	@python3 tools/check_outcomes.py
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
