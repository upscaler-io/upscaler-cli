.PHONY: install check-venv test lint format

# `sys.prefix != sys.base_prefix` is the standard "am I inside a virtualenv"
# test. Installing outside one silently lands this package plus every dev tool
# in the ambient interpreter (with pyenv, the shim makes `pip` resolve to
# something no matter what, so there is no error to notice). Set
# SKIP_VENV_CHECK=1 where the environment is already isolated: CI runners,
# containers, tox.
check-venv:
	@if [ -z "$(SKIP_VENV_CHECK)" ] && \
	   ! python3 -c "import sys; sys.exit(0 if sys.prefix != sys.base_prefix else 1)" 2>/dev/null; then \
		echo "make install: refusing to install outside a virtualenv."; \
		echo ""; \
		echo "  python3 -m venv .venv && source .venv/bin/activate && make install"; \
		echo ""; \
		echo "Already isolated (CI, container)? Use: SKIP_VENV_CHECK=1 make install"; \
		exit 1; \
	fi

install: check-venv
	pip install -e ".[dev]"

test:
	python -m pytest tests/ -v --tb=short

lint:
	flake8 upscaler_cli/ tests/ --max-line-length=100
	isort --check-only upscaler_cli/ tests/ --profile=black --line-length=100

format:
	black upscaler_cli/ tests/ --line-length=100
	isort upscaler_cli/ tests/ --profile=black --line-length=100
