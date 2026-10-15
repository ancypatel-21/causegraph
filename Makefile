COMPOSE = docker compose -f infra/compose/docker-compose.yml
RUN_CLI = $(COMPOSE) run --rm benchmark-cli

.PHONY: up down logs ps bootstrap-db smoke scenario test lint fmt

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down -v

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

bootstrap-db:
	$(RUN_CLI) bootstrap-db

# One command to run a smoke benchmark (spec section 17).
smoke: up bootstrap-db
	$(RUN_CLI) run-scenario data-schema-001

scenario: bootstrap-db
	$(RUN_CLI) run-scenario $(SCENARIO)

test:
	pytest

lint:
	ruff check .

fmt:
	black .
	ruff check --fix .
