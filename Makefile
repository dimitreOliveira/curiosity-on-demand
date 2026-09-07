-include .env

# Help documentation
help:
	@echo "Available commands:"
	@echo "  Local development:"
	@echo "    make setup           - Install dependencies and Playwright Chromium using uv"
	@echo "    make build           - Install dependencies and sync local environment using uv sync --frozen"
	@echo "    make run             - Start the Telegram bot research service"
	@echo "    make lint            - Run linting and formatting (codespell, ruff, ty) on backend"
	@echo "    make test            - Run all backend tests using pytest"
	@echo ""
	@echo "  Docker operations:"
	@echo "    make docker-build    - Build project Docker images using Docker Compose"
	@echo "    make docker-lint     - Run linting suite inside a temporary project container"
	@echo "    make docker-test     - Run test suite inside a temporary project container"
	@echo "    make docker-notebook - Launch Jupyter server inside Docker container (port 8888)"
	@echo "    make docker-start    - Build and start the entire service stack using Compose"
	@echo "    make docker-stop     - Shutdown and remove active Docker Compose containers"

# Local commands
setup:
	uv sync
	uv run playwright install chromium

build:
	uv sync --frozen

run:
	uv run python main.py

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
	docker compose build --progress=plain || docker-compose --progress=plain build

docker-lint: docker-build
	docker compose run --rm app make lint || docker-compose run --rm app make lint

docker-test: docker-build
	docker compose run --rm app make test || docker-compose run --rm app make test

docker-notebook: docker-build
	docker compose run --rm -p 8888:8888 app jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --allow-root --ServerApp.token='' --ServerApp.password='' --ServerApp.disable_check_xsrf=True --ServerApp.allow_origin='*' --ServerApp.allow_remote_access=True || docker-compose run --rm -p 8888:8888 app jupyter lab --ip=0.0.0.0 --port=8888 --no-browser --allow-root --ServerApp.token='' --ServerApp.password='' --ServerApp.disable_check_xsrf=True --ServerApp.allow_origin='*' --ServerApp.allow_remote_access=True

docker-start: docker-build
	docker compose up || docker-compose up

docker-stop:
	docker compose down || docker-compose down