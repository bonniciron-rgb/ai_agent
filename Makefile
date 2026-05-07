.PHONY: install lint format test typecheck check clean

install:
	pip install -e ".[dev,data,features,backtest,agent,bot,broker]"

lint:
	ruff check .

format:
	ruff format .

format-check:
	ruff format --check .

test:
	pytest -q

typecheck:
	mypy

check: lint format-check test

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist *.egg-info
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
