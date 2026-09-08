# The .deb, the .rpm and the wheel, built the way statemachined builds its own.
#
# Two things this is, and one it is not.
#
# **Vendored.** A self-contained Python tree lands under /opt/braemons/triald --
# interpreter and all -- rather than a set of `python3-*` dependencies. That is
# the braemons pattern and the reason is a rig rather than taste: an OS upgrade
# that moves Python must not be able to stop an experiment, and a box in a rack
# should not need a working pip to be repaired. The price is that a pure-Python
# package is per-architecture.
#
# **Built in a pinned container.** `packages-amd64` and `packages-arm64` build
# inside packaging/docker/Dockerfile.package-builder, whose base image and every
# tool in it are pinned by digest or version, and whose file mtimes come from
# the commit rather than from the clock. So the artifact is a function of the
# commit and this repository, not of who ran it -- which is what makes a CI
# build and a developer's build comparable.
#
# What it is **not** is a cross-compile. Nothing here is compiled at all, but
# the vendored interpreter and the numpy/scipy wheels beside it are native
# artifacts, so the arm64 package is built by running the builder image *as*
# arm64 under qemu. Register the handler once per boot:
#
#     docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
#
#     make -C packaging packages-arm64    # the Pi 5, beside vstimd and statemachined
#     make -C packaging packages          # both architectures, both formats
#     make -C packaging deb               # this machine, no container: fast
#     make -C packaging wheel             # the wheel and the sdist, for a release
#     make -C packaging check             # run the staged tree, package nothing

ROOT  := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
BUILD := $(ROOT)/build/package
STAGE := $(BUILD)/root
SRC   := $(BUILD)/src

DIST_DIR ?= $(ROOT)/dist

PACKAGE_BUILDER_IMAGE ?= triald-package-builder

# Where the tree lands on the target: the path the launcher's shebang, the
# systemd unit and nfpm.yaml all name. Changing it means changing all three.
PREFIX := /opt/braemons/triald

# The interpreter uv fetches from python-build-standalone. Pinned here because
# the package is built out of it: a rig and CI disagreeing about which Python
# ran the daemon is exactly the difference this vendoring exists to remove.
PYTHON_VERSION ?= 3.12

# In the package on purpose, and not in pyproject.toml's dependencies.
#
# `dependencies = []` in the core is load-bearing -- the domain logic, the
# policy API and the simulator import with nothing installed, and that is what
# makes them testable and what keeps `triald sim` fast. But a rig is not a
# checkout: without numpy, "scriptable in Python" is a hollow promise, and
# discovering that at 2 a.m. because a policy will not load is the failure this
# exists to prevent. So they are installed into the staged tree here, where they
# are a property of the *package* rather than of the library.
#
# PsychoPy is deliberately absent and must stay so: it drags pyglet, wx and a
# GUI stack onto a headless rig box. Labs that want QuestHandler install it into
# this same vendored interpreter, which is ABI-compatible by construction
# because there is only one interpreter.
RIG_EXTRAS ?= numpy scipy

UV   ?= uv
NFPM ?= nfpm
NFPM_PIN := 2.43.1

# ── The version, from the one place it is defined ───────────────────────────
#
# Override to build outside a tagged checkout; the packaging container does
# exactly that, since its build context has no .git:
#
#     make -C packaging deb TRIALD_VERSION=0.1.0
#
# An explicit value short-circuits the script rather than being handed to it.
TRIALD_VERSION ?=
RESOLVED_VERSION := $(strip $(if $(strip $(TRIALD_VERSION)),$(strip $(TRIALD_VERSION)),\
                      $(shell $(ROOT)/packaging/scripts/git-version.sh 2>/dev/null)))
RESOLVED_PY_VERSION := $(strip $(if $(strip $(TRIALD_VERSION)),\
                         $(shell TRIALD_VERSION='$(strip $(TRIALD_VERSION))' \
                                 $(ROOT)/packaging/scripts/git-version.sh --pep440 2>/dev/null),\
                         $(shell $(ROOT)/packaging/scripts/git-version.sh --pep440 2>/dev/null)))

# Missing version = hard stop, never a default: every path below bakes it into
# a filename and into package metadata, so continuing with an invented one
# would produce artifacts that lie about what they are.
#
# Recursive (`=`, not `:=`) so the error fires where VERSION is *used* rather
# than when this file is parsed, which keeps `clean` and `install-nfpm` working
# in a checkout with no tags.
VERSION    = $(or $(RESOLVED_VERSION),$(error Cannot determine the version. Run \
packaging/scripts/git-version.sh to see why, or pass TRIALD_VERSION=<version>))
PY_VERSION = $(or $(RESOLVED_PY_VERSION),$(error Cannot determine the version))

REVISION ?= 1

MAINTAINER ?= Joscha Schmiedt <joscha.schmiedt@gmail.com>

# Every mtime in the package, from the commit rather than from the clock. Two
# builds of one commit otherwise share not a single byte, which makes "did this
# artifact come from that source" unanswerable.
ifndef SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH := $(shell git -C $(ROOT) log -1 --format=%ct 2>/dev/null || echo 0)
endif
MTIME := $(shell date -u -d @$(SOURCE_DATE_EPOCH) +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)
export SOURCE_DATE_EPOCH

# nfpm speaks Go's names for architectures, which are also dpkg's for the two
# that matter. Derived rather than asked for: a package labelled with an
# architecture it was not built on is worse than one that will not build.
UNAME_M := $(shell uname -m)
ARCH := $(strip \
  $(if $(filter x86_64,$(UNAME_M)),amd64, \
  $(if $(filter aarch64 arm64,$(UNAME_M)),arm64, \
  $(if $(filter armv7l,$(UNAME_M)),arm7,))))

# Documentation that ships in the package, because the box in the rack is where
# somebody is standing when they need it.
DOCS := README.md LICENSE dev/API.md dev/PLAN.md

.PHONY: packages-amd64 packages-arm64 packages packages-here package-in-container \
        deb rpm wheel stage stage-docs stage-deterministic check inspect repro \
        print-version install-nfpm clean help

# ── Built in the pinned container, one per architecture ─────────────────────

packages-amd64:             ## the .deb and .rpm for amd64, in the pinned image
	@$(MAKE) --no-print-directory package-in-container PLATFORM=linux/amd64 TAG=amd64

packages-arm64:             ## the same for arm64 -- the Pi 5 -- under qemu
	@$(MAKE) --no-print-directory package-in-container PLATFORM=linux/arm64 TAG=arm64

packages: packages-amd64 packages-arm64  ## every package a release publishes

package-in-container:
	@mkdir -p $(DIST_DIR)
	cd $(ROOT) && DOCKER_BUILDKIT=1 docker build \
	  --platform $(PLATFORM) \
	  -f packaging/docker/Dockerfile.package-builder \
	  --build-arg TRIALD_VERSION=$(VERSION) \
	  --build-arg SOURCE_DATE_EPOCH=$(SOURCE_DATE_EPOCH) \
	  -t $(PACKAGE_BUILDER_IMAGE)-$(TAG) .
	docker run --rm --platform $(PLATFORM) \
	  -v $(abspath $(DIST_DIR)):/output $(PACKAGE_BUILDER_IMAGE)-$(TAG)

# What the container runs. Not for direct use on a dev box -- it assumes the
# image's tools and does no Docker work itself -- but it is the same recipe
# `make deb` uses here, so there is one definition of how a package is built.
packages-here: deb rpm

# ── Built on this machine, for iterating ────────────────────────────────────

deb: check                  ## the .deb for this machine, no container
	@mkdir -p $(DIST_DIR)
	cd $(ROOT) && $(NFPM) package -f packaging/nfpm.yaml -p deb -t $(DIST_DIR)

rpm: check                  ## the .rpm for this machine, no container
	@mkdir -p $(DIST_DIR)
	cd $(ROOT) && $(NFPM) package -f packaging/nfpm.yaml -p rpm -t $(DIST_DIR)

deb rpm: export TRIALD_ARCH        = $(ARCH)
deb rpm: export TRIALD_MAINTAINER  = $(MAINTAINER)
deb rpm: export TRIALD_RELEASE     = $(REVISION)
deb rpm: export TRIALD_PKG_VERSION = $(VERSION)

# ── The wheel, which is not the same artifact as the package ────────────────
#
# The package is for a rig: a whole interpreter, a unit file, a user. The wheel
# is for everything else that has to *import* triald -- the end-to-end tests
# across the three daemons, statemachined's `e2e` dependency group, somebody's
# analysis notebook -- none of which want a system daemon installed to get at
# the outcome taxonomy.
#
# Architecture-independent, so one of these serves every rig, and built from a
# stamped copy for the same reason the package is: pyproject.toml carries the
# 0.0.0 sentinel in the repository, and a build must never leave the working
# tree dirty.
wheel: $(SRC)/pyproject.toml  ## the wheel and the sdist, stamped, into dist/
	@mkdir -p $(DIST_DIR)
	$(UV) build --project $(SRC) --out-dir $(DIST_DIR)
	@ls -1 $(DIST_DIR)/*.whl $(DIST_DIR)/*.tar.gz

# ── The staged tree ─────────────────────────────────────────────────────────

# The source, with the version stamped in. Separate from the tree below because
# `wheel` needs it and does not need a vendored interpreter.
$(SRC)/pyproject.toml: $(shell find $(ROOT)/src -type f) $(ROOT)/pyproject.toml
	rm -rf $(SRC)
	@mkdir -p $(SRC)
	cp -a $(ROOT)/src $(ROOT)/pyproject.toml $(ROOT)/README.md $(ROOT)/LICENSE $(SRC)/
	sed -i 's/^version = "0.0.0"$$/version = "$(PY_VERSION)"/' $(SRC)/pyproject.toml
	@grep -q '^version = "$(PY_VERSION)"$$' $(SRC)/pyproject.toml || { \
	  echo "error: the version sentinel in pyproject.toml did not match."; \
	  echo "       Nothing was stamped, and a 0.0.0 artifact is one nobody"; \
	  echo "       can correlate with a commit. Fix the sed above."; exit 1; }
	@touch $@

stage: $(STAGE)/.stamp      ## build the tree the package is cut from
$(STAGE)/.stamp: $(SRC)/pyproject.toml
	@test -n "$(ARCH)" || { \
	  echo "error: no nfpm architecture known for $(UNAME_M)."; \
	  echo "       Build on the target architecture, or add it above."; exit 1; }
	rm -rf $(STAGE)
	@mkdir -p $(STAGE)$(PREFIX) $(DIST_DIR)

	@#  The interpreter, copied out of uv's managed store rather than symlinked
	@#  into it. --managed-python so this cannot silently vendor whatever Python
	@#  happens to be on PATH, which would defeat the entire exercise.
	$(UV) python install --managed-python $(PYTHON_VERSION)
	cp -a "$$(dirname $$(dirname $$($(UV) python find --managed-python $(PYTHON_VERSION))))/." \
	  $(STAGE)$(PREFIX)/
	@#  uv marks its own installs externally managed so that nothing writes into
	@#  the store. This copy is not that store: it is a tree being built into a
	@#  package, and the daemon is about to be installed into it.
	find $(STAGE)$(PREFIX) -name EXTERNALLY-MANAGED -delete

	@#  The dependencies come from uv.lock, exported with hashes, rather than
	@#  being resolved against PyPI at build time. Otherwise a release of fastapi
	@#  between two builds of one commit changes the artifact, which is the
	@#  difference between "reproducible" and "reproducible this afternoon".
	@#  Exported from the unmodified root because that is where the lock matches
	@#  its pyproject; the project itself then goes in --no-deps.
	$(UV) export --project $(ROOT) --frozen --extra serve --no-default-groups \
	  --no-emit-project --no-header --no-annotate \
	  --format requirements.txt -o $(BUILD)/requirements.txt
	$(UV) pip install --python $(STAGE)$(PREFIX)/bin/python3 \
	  --link-mode=copy --no-cache --quiet -r $(BUILD)/requirements.txt
	@#  See RIG_EXTRAS above for why these are here and not in pyproject.toml.
	$(UV) pip install --python $(STAGE)$(PREFIX)/bin/python3 \
	  --link-mode=copy --no-cache --quiet $(RIG_EXTRAS)
	$(UV) pip install --python $(STAGE)$(PREFIX)/bin/python3 \
	  --link-mode=copy --no-cache --quiet --no-deps $(SRC)

	@#  Nothing in here is a development environment: no headers, no pip, no
	@#  tkinter, and no console scripts but ours -- the ones uv writes carry the
	@#  *build* machine's path to the interpreter, so shipping them would ship a
	@#  handful of commands that are broken on every target.
	rm -rf $(STAGE)$(PREFIX)/include $(STAGE)$(PREFIX)/share
	rm -rf $(STAGE)$(PREFIX)/lib/python*/idlelib $(STAGE)$(PREFIX)/lib/python*/tkinter \
	       $(STAGE)$(PREFIX)/lib/python*/lib2to3 $(STAGE)$(PREFIX)/lib/python*/ensurepip \
	       $(STAGE)$(PREFIX)/lib/python*/site-packages/pip \
	       $(STAGE)$(PREFIX)/lib/python*/site-packages/pip-*.dist-info
	find $(STAGE)$(PREFIX)/bin -mindepth 1 \
	  -not -name python -not -name python3 -not -name 'python3.[0-9]*' -delete
	rm -f $(STAGE)$(PREFIX)/bin/*-config
	rm -f $(STAGE)$(PREFIX)/BUILD

	@#  One launcher, written here rather than taken from the wheel, so that the
	@#  shebang is the installed path and not this machine's staging directory.
	@printf '%s\n' \
	  '#!$(PREFIX)/bin/python3' \
	  '# The installed entry point. See packaging/Makefile for why it is not' \
	  '# the console script the wheel carries.' \
	  'import sys' \
	  'from triald.cli import main' \
	  '' \
	  'if __name__ == "__main__":' \
	  '    sys.exit(main())' \
	  > $(STAGE)$(PREFIX)/bin/triald
	chmod 0755 $(STAGE)$(PREFIX)/bin/triald

	$(MAKE) --no-print-directory stage-docs stage-deterministic
	@touch $@

stage-docs:
	@mkdir -p $(STAGE)/usr/share/doc/braemons-triald
	@for doc in $(DOCS); do cp $(ROOT)/$$doc $(STAGE)/usr/share/doc/braemons-triald/; done

# What makes two builds of one commit the same bytes. Three things drift, and
# the order below is the fix for all three -- see statemachined's copy of this
# rule for the long version. uv's per-install `uv_cache.json`, every mtime in
# the tree, and the .pyc files that normalising those mtimes invalidates.
stage-deterministic:
	@find $(STAGE)$(PREFIX)/lib/python*/site-packages -name uv_cache.json -delete
	@sed -i '/uv_cache\.json/d' \
	  $(STAGE)$(PREFIX)/lib/python*/site-packages/*.dist-info/RECORD
	@find $(STAGE) -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
	@find $(STAGE) -exec touch --no-dereference -d @$(SOURCE_DATE_EPOCH) {} +
	@$(STAGE)$(PREFIX)/bin/python3 -m compileall -q -f \
	  --invalidation-mode unchecked-hash \
	  -s $(STAGE) -p / \
	  $(STAGE)$(PREFIX)/lib/python$(PYTHON_VERSION) >/dev/null
	@find $(STAGE) -exec touch --no-dereference -d @$(SOURCE_DATE_EPOCH) {} +
	@echo "  deterministic: mtimes at $(MTIME), hash-based .pyc throughout"

# ── Before it is a package ──────────────────────────────────────────────────

# The staged tree, run. Every other test in this repository runs the daemon out
# of a checkout with uv building the environment; this is the only thing that
# runs the interpreter that is about to be shipped, with the dependencies that
# are about to be shipped.
check: stage                ## run the staged daemon: imports, routes, the unit's own command line
	@PYTHONDONTWRITEBYTECODE=1 $(STAGE)$(PREFIX)/bin/python3 \
	  $(ROOT)/packaging/scripts/check-staged-tree.py
	@#  The launcher cannot be run by its own shebang here: that shebang is the
	@#  *installed* interpreter, which is the whole point of writing it by hand,
	@#  and it does not exist on this machine.
	@PYTHONDONTWRITEBYTECODE=1 $(STAGE)$(PREFIX)/bin/python3 \
	  $(STAGE)$(PREFIX)/bin/triald --help >/dev/null
	@head -1 $(STAGE)$(PREFIX)/bin/triald | grep -qxF '#!$(PREFIX)/bin/python3' \
	  || { echo "error: the launcher's shebang is not $(PREFIX)/bin/python3"; exit 1; }
	@echo "  the launcher runs, and names $(PREFIX)/bin/python3"
	@echo "  version $(VERSION)  (python: $(PY_VERSION))"
	@echo "  staged tree $$(du -sh $(STAGE) | cut -f1), for $(ARCH)"

inspect:                    ## list what the built packages contain
	@for deb in $(DIST_DIR)/*.deb; do \
	  echo "== $$deb"; dpkg-deb -I "$$deb"; \
	  dpkg-deb -c "$$deb" | awk '{print $$6}' | grep -v '$(PREFIX)/lib' | sort; \
	done

# The reproducibility claim, checked rather than asserted: build, keep the
# checksum, wipe everything, build again, compare. It is a claim worth checking
# because it fails silently -- one file carrying a wall-clock timestamp is
# enough, and the artifact still installs perfectly.
repro:                      ## build the .deb twice and prove the bytes match
	@$(MAKE) --no-print-directory clean >/dev/null
	@$(MAKE) --no-print-directory deb >/dev/null
	@first=$$(sha256sum $(DIST_DIR)/*.deb | cut -d' ' -f1); \
	 $(MAKE) --no-print-directory clean >/dev/null; \
	 $(MAKE) --no-print-directory deb >/dev/null; \
	 second=$$(sha256sum $(DIST_DIR)/*.deb | cut -d' ' -f1); \
	 if [ "$$first" = "$$second" ]; then \
	   echo "reproducible: $$first"; \
	 else \
	   echo "NOT reproducible:"; echo "  $$first"; echo "  $$second"; \
	   echo "  Compare with: diffoscope, or ar x both and diff the tars."; \
	   exit 1; \
	 fi

print-version:              ## the version this checkout would build
	@echo $(VERSION)

install-nfpm:               ## the pinned nfpm, into ~/.local/bin
	@mkdir -p $(HOME)/.local/bin
	@case "$(UNAME_M)" in \
	  x86_64)  a=x86_64 ;; \
	  aarch64) a=arm64  ;; \
	  *) echo "no nfpm build for $(UNAME_M)" >&2; exit 1 ;; \
	esac; \
	curl -fsSL -o /tmp/nfpm.tar.gz \
	  "https://github.com/goreleaser/nfpm/releases/download/v$(NFPM_PIN)/nfpm_$(NFPM_PIN)_Linux_$$a.tar.gz"
	tar xzf /tmp/nfpm.tar.gz -C $(HOME)/.local/bin nfpm
	rm -f /tmp/nfpm.tar.gz
	@$(HOME)/.local/bin/nfpm --version | head -2

clean:
	rm -rf $(BUILD) $(DIST_DIR)

help:
	@grep -E '^[a-z][a-z0-9-]*:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
