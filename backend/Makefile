.DEFAULT_GOAL := help
.PHONY: help install run run-worker run-cli migrate seed test lint compose-up compose-down

help:
	@echo "install | migrate | seed | run | run-worker | run-cli | test | lint | compose-up | compose-down"
install:
	uv sync --frozen
run:
	uv run python -m app.cli serve --host 0.0.0.0
run-worker:
	uv run python -m app.cli worker
run-cli:
	uv run python -m app.cli chat
migrate:
	uv run python -m app.cli migrate
seed:
	uv run python -m app.cli seed
test:
	uv run pytest -q
lint:
	uv run ruff check app alembic tests
compose-up:
	docker compose -f ../compose.yaml up -d postgres redis minio etcd milvus
compose-down:
	docker compose -f ../compose.yaml stop
