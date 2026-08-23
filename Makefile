-include .env

# Help documentation
help:
	@echo "Available commands:"
	@echo "  Local development:"
	@echo "    make build           - Install dependencies and sync local environment using uv"
	@echo "    make lint            - Run linting and formatting (codespell, ruff, ty) on backend"
	@echo "    make test            - Run all backend tests using pytest"
	@echo ""
	@echo "  Docker operations:"
	@echo "    make docker-build    - Build project Docker images using Docker Compose"
	@echo "    make docker-lint     - Run linting suite inside a temporary project container"
	@echo "    make docker-start    - Build and start the entire service stack using Compose"
	@echo "    make docker-stop     - Shutdown and remove active Docker Compose containers"

# Local commands
build:
	uv sync --frozen

venv:
	@echo source .venv/bin/activate

lint:
	uv run codespell
	uv run ruff check --select I --fix
	uv run ruff check --fix
	uv run ruff format
	uv run ty check

test:
	uv run pytest tests

# Docker commands
docker-build:
	docker-compose --progress=plain build

docker-lint: docker-build
	docker-compose run --rm make lint

docker-start: docker-build
	docker-compose up

docker-stop:
	docker-compose down