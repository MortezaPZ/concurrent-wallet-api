.PHONY: help install db migrate run test test-concurrency lint format schema clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "%-18s %s\n", $$1, $$2}'

install:  ## Create the virtualenv and install dependencies
	python -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

db:  ## Start PostgreSQL in Docker
	docker compose up -d --wait postgres

migrate:  ## Apply migrations
	python manage.py migrate

run:  ## Start the development server
	python manage.py runserver

test:  ## Run the whole suite against PostgreSQL
	pytest -v

test-concurrency:  ## Run only the parallel-session tests
	pytest -v -m concurrency

lint:  ## Lint and check formatting
	ruff check .
	ruff format --check .

format:  ## Apply formatting
	ruff format .
	ruff check --fix .

schema:  ## Write the OpenAPI schema to openapi.yaml
	python manage.py spectacular --file openapi.yaml

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage coverage.xml
