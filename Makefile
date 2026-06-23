.PHONY: up down restart build test lint

up:
	docker compose up -d

down:
	docker compose down -v

restart:
	docker compose down -v && docker compose up -d --build

build:
	docker compose up -d --build

test:
	docker compose exec app python -m pytest tests/ -v

lint:
	docker compose exec app ruff check app/ tests/
