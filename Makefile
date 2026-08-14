.PHONY: install test lint format

install:
	pip install -e ".[dev]"

test:
	python -m pytest tests/ -v --tb=short

lint:
	flake8 upscaler_cli/ tests/ --max-line-length=100
	isort --check-only upscaler_cli/ tests/ --profile=black --line-length=100

format:
	black upscaler_cli/ tests/ --line-length=100
	isort upscaler_cli/ tests/ --profile=black --line-length=100
