# Convenience wrappers. Everything here is `uv` underneath; run the uv commands
# directly if you prefer.

.PHONY: help sync test lint fmt typecheck check sim clean version

help:
	@echo "make sync       install the dev environment"
	@echo "make test       run the test suite"
	@echo "make lint       ruff check + format --check"
	@echo "make fmt        ruff format"
	@echo "make typecheck  ty check"
	@echo "make check      lint + typecheck + test + a simulated session"
	@echo "make sim        run a simulated session"
	@echo "make version    the version the git tag implies"

sync:
	uv sync --group dev

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .

typecheck:
	uv run ty check

# What CI runs. The simulated session is the end-to-end smoke test.
check: lint typecheck test
	uv run triald sim --trials 200
	uv run triald policy check examples/staircase.py --trial-types contrast_0,contrast_1,contrast_2,contrast_3,contrast_4,contrast_5

sim:
	uv run triald sim --trials 200 --trace

version:
	@sh packaging/scripts/git-version.sh

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov dist build
