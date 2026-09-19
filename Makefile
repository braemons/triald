# Convenience wrappers. Everything here is `uv` underneath; run the uv commands
# directly if you prefer.
#
# `--directory daemon` on every one of them: the Python project is `daemon/`,
# beside `client/` and `proto/`, so that this repository has the shape every
# braemons daemon repository has (contracts/DAEMON_LAYOUT.md). The alternative
# was a pyproject.toml at the root claiming the whole tree is one package, which
# it is not.

.PHONY: help sync test lint fmt typecheck check sim clean version \
        proto check-proto web check-web client deb wheel packages package-check

help:
	@echo "make sync       install the dev environment"
	@echo "make test       run the test suite"
	@echo "make lint       ruff check + format --check"
	@echo "make fmt        ruff format"
	@echo "make typecheck  ty check"
	@echo "make check      lint + typecheck + test + the proto + a simulated session"
	@echo "make proto      regenerate daemon/src/triald/_proto/ from proto/"
	@echo "make check-proto  the proto compiles, is current, and matches the taxonomy"
	@echo "make web        regenerate client/web/elements/daemon_api_client.js from proto/"
	@echo "make check-web  the committed browser client is what proto/ produces"
	@echo "make client     the Python client's own checks (its own project)"
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

# `--all-extras`: `serve` and `stimulus` are optional at runtime and the code
# guards their imports, but a type checker that cannot see fastapi reports the
# whole serving layer as unresolved. Without this the target fails on a clean
# checkout, which is how it was failing before anybody noticed.
typecheck:
	uv run --directory daemon --all-extras --group dev ty check

# `proto/triald/v1/` is this daemon's public API — types and behaviours both
# (contracts/DAEMON_LAYOUT.md). All of it is authored by hand, including the
# outcome taxonomy: it used to be a JSON file with vendored copies and a regex
# checker, and a protobuf enum is the thing that file was imitating.
#
# Two checks, catching two different mistakes: protoc catches a file that does
# not parse, and check_outcomes.py catches a copy of the taxonomy that drifted
# from the enum. The generated code is committed, so a checkout runs without
# protoc and an interface change arrives as a diff a reviewer can read
# (contracts/DAEMON_LAYOUT.md).
#
# There was a third — `check_routes.py`, holding a hand-maintained router to
# the rpcs by reading source code with regexes. The API is gRPC now: an rpc's
# address is `/triald.v1.Session/Arm`, written down nowhere and impossible to
# get wrong, and `tests/test_every_rpc_is_implemented.py` reads the descriptor
# to catch an rpc nothing implements. Both jobs done better, so it is gone.
proto: ## regenerate daemon/src/triald/_proto/ from proto/
	@$(MAKE) --no-print-directory generate-into OUT=daemon/src/triald/_proto
	@echo "daemon/src/triald/_proto/"

# service.proto is generated now, and with service stubs: the API is gRPC, so
# the servicer base classes it produces are what `api/servicers/` implements —
# and an rpc with no implementation is caught by the generated stub rather than
# by a checker reading source code with regexes.
# **The import rewrite is why this is a target and not a command.**
#
# protoc roots a generated module's imports at the proto path, so the stubs
# reach each other as `from triald.v1 import common_pb2` — and `triald` is this
# package, so that only resolves through a `__path__` trick no static checker
# can follow. It also cannot work at all for `from braemons.v1 import ...`,
# which has no package here to hang off.
#
# So the generated imports are rewritten to be absolute inside `_proto/`. It is
# one sed over three file kinds, `check-proto` compares the rewritten output so
# nothing drifts back, and `client/python/Makefile` does the same thing for the
# same reason.
generate-into:
	@mkdir -p $(OUT)
	@uv run --directory daemon --group dev python -m grpc_tools.protoc \
	  --proto_path=../proto \
	  --python_out=../$(OUT) --pyi_out=../$(OUT) --grpc_python_out=../$(OUT) \
	  $(patsubst proto/%,../proto/%,$(PROTOS))
	@find $(OUT) -name '*.py' -o -name '*.pyi' | xargs sed -i \
	  -e 's/^from triald\.v1 import /from triald._proto.triald.v1 import /' \
	  -e 's/^from braemons\.v1 import /from triald._proto.braemons.v1 import /'

# Both packages: `triald/v1/` is this daemon's interface, and `braemons/v1/`
# holds what the family agrees on — today the `.tdr` outcome taxonomy, which
# statemachined speaks too and neither daemon owns.
PROTOS := $(wildcard proto/triald/v1/*.proto) $(wildcard proto/braemons/v1/*.proto)

check-proto: ## the proto compiles, is current, and matches the taxonomy
	@protoc --proto_path=proto --descriptor_set_out=/dev/null \
	  proto/triald/v1/*.proto proto/braemons/v1/*.proto
	@# Into a scratch directory and compared, rather than regenerated in place
	@# and handed to `git diff`: the git version is vacuous for a file git does
	@# not track yet, which is exactly when a new generator is least trusted.
	@rm -rf build/proto-check
	@$(MAKE) --no-print-directory generate-into OUT=build/proto-check
	@diff -r -x '__pycache__' build/proto-check daemon/src/triald/_proto >/dev/null || { \
	  echo "daemon/src/triald/_proto/ is not what proto/ produces — the interface changed:"; \
	  diff -rq -x '__pycache__' build/proto-check daemon/src/triald/_proto || true; \
	  echo "run 'make proto' and commit the result with the change that caused it."; \
	  exit 1; \
	}
	@rm -rf build/proto-check
	@python3 tools/check_outcomes.py

# **The browser's protobuf client is generated and committed**, like
# daemon/src/triald/_proto/ and for the same reason: a checkout runs with uv
# alone. `packaging/Makefile` copies `client/web/` into the wheel, so a bundle
# produced at package time would make npm a build dependency of every release.
# It is not. `npm ci` installs exactly what package-lock.json pins, so the
# bundle is reproducible; `check-web` is what holds it to the proto.
web: ## regenerate client/web/elements/daemon_api_client.js from proto/
	@cd client/web && npm ci --silent --no-audit --no-fund && node build_daemon_api_client.mjs

check-web: ## fail if the committed browser client is not what proto/ produces
	@mkdir -p build
	@cp client/web/elements/daemon_api_client.js build/web-check.js 2>/dev/null || true
	@$(MAKE) --no-print-directory web
	@diff -q build/web-check.js client/web/elements/daemon_api_client.js >/dev/null || { \
	  echo "client/web/elements/daemon_api_client.js is not what proto/ produces:"; \
	  diff build/web-check.js client/web/elements/daemon_api_client.js | head -20; \
	  echo "it has been regenerated — commit it with the change that caused it."; \
	  exit 1; \
	}
	@rm -f build/web-check.js

# The Python client is its own project with its own Makefile, and is not part
# of `check` for the same reason `check-web` is not: it needs a network the
# first time. Its own `check` regenerates its stubs from proto/, lints,
# typechecks and runs both suites — the second of which starts this daemon.
client: ## the Python client's checks: its stubs, ruff, ty, and both suites
	@$(MAKE) --no-print-directory -C client/python check

# What CI runs. The simulated session is the end-to-end smoke test.
#
# Not check-web and not client: both need a network the first time, and this
# target has to work on a rig. CI runs each as its own step.
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
