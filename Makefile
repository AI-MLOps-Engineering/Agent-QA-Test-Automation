# Makefile - tâches utiles pour développement, build et tests
# Usage: make <target>
# Exemple: make build-all && make compose-up

# Configuration
DOCKER_COMPOSE ?= docker-compose
IMAGE_PREFIX ?= agent-qa
COMPOSE_FILE ?= docker-compose.yml
PROJECT_NAME ?= agent_qa

# Services names (doivent correspondre aux services dans docker-compose.yml)
API_SERVICE ?= api
FRONTEND_SERVICE ?= frontend
MODEL_SERVICE ?= model
VECTORSTORE_SERVICE ?= vectorstore
SANDBOX_IMAGE ?= $(IMAGE_PREFIX)-sandbox:latest

# Default target
.PHONY: help
help:
    @echo "Makefile - targets disponibles:"
    @echo "  make build-all         Build toutes les images (api, frontend, model, sandbox)"
    @echo "  make build-api         Build image API"
    @echo "  make build-frontend    Build image frontend"
    @echo "  make build-model       Build image model (placeholder)"
    @echo "  make build-sandbox     Build image sandbox runner"
    @echo "  make compose-build     docker-compose build"
    @echo "  make compose-up        docker-compose up (foreground)"
    @echo "  make compose-upd       docker-compose up -d (detached)"
    @echo "  make compose-down      docker-compose down --volumes"
    @echo "  make logs SERVICE=api  Tail logs for a service (default: api)"
    @echo "  make shell SERVICE=api Open a shell in a running service container"
    @echo "  make test-unit         Run unit tests (pytest) locally"
    @echo "  make test-integration  Run integration tests (requires services up)"
    @echo "  make clean             Remove python caches and temp build artifacts"

# -------------------------
# Build images
# -------------------------
.PHONY: build-all build-api build-frontend build-model build-sandbox
build-all: build-api build-frontend build-model build-sandbox

build-api:
    @echo "Building API image..."
    $(DOCKER_COMPOSE) -f $(COMPOSE_FILE) build $(API_SERVICE)

build-frontend:
    @echo "Building frontend image..."
    $(DOCKER_COMPOSE) -f $(COMPOSE_FILE) build $(FRONTEND_SERVICE)

build-model:
    @echo "Building model image..."
    $(DOCKER_COMPOSE) -f $(COMPOSE_FILE) build $(MODEL_SERVICE)

build-sandbox:
    @echo "Building sandbox image..."
    $(DOCKER_COMPOSE) -f $(COMPOSE_FILE) build sandbox-runner

# -------------------------
# Docker Compose helpers
# -------------------------
.PHONY: compose-build compose-up compose-upd compose-down
compose-build:
    $(DOCKER_COMPOSE) -f $(COMPOSE_FILE) build

compose-up:
    $(DOCKER_COMPOSE) -f $(COMPOSE_FILE) up

compose-upd:
    $(DOCKER_COMPOSE) -f $(COMPOSE_FILE) up -d

compose-down:
    $(DOCKER_COMPOSE) -f $(COMPOSE_FILE) down --volumes --remove-orphans

# -------------------------
# Logs and shell
# -------------------------
.PHONY: logs shell
logs:
    @SERVICE=$(or $(SERVICE),$(API_SERVICE)); \
    echo "Tailing logs for $$SERVICE..."; \
    $(DOCKER_COMPOSE) -f $(COMPOSE_FILE) logs -f $$SERVICE

shell:
    @SERVICE=$(or $(SERVICE),$(API_SERVICE)); \
    CONTAINER=$$($(DOCKER_COMPOSE) -f $(COMPOSE_FILE) ps -q $$SERVICE); \
    if [ -z "$$CONTAINER" ]; then echo "Service $$SERVICE not running"; exit 1; fi; \
    echo "Opening shell in $$SERVICE (container $$CONTAINER)"; \
    docker exec -it $$CONTAINER /bin/bash || docker exec -it $$CONTAINER /bin/sh

# -------------------------
# Tests
# -------------------------
# Run unit tests locally (requires pytest installed in the dev environment)
.PHONY: test-unit
test-unit:
    @echo "Running unit tests..."
    pytest -q tests/unit

# Integration tests: expects API service to be reachable (docker-compose up -d)
.PHONY: test-integration
test-integration:
    @echo "Running integration tests..."
    pytest -q tests/integration

# -------------------------
# Utility / cleanup
# -------------------------
.PHONY: clean
clean:
    @echo "Cleaning python caches and temporary files..."
    find . -type d -name "__pycache__" -exec rm -rf {} + || true
    find . -type f -name "*.pyc" -delete || true
    rm -rf .pytest_cache || true

# Convenience: rebuild API and restart service
.PHONY: rebuild-api-restart
rebuild-api-restart: build-api
    $(DOCKER_COMPOSE) -f $(COMPOSE_FILE) up -d --no-deps --build $(API_SERVICE)
    @echo "API rebuilt and restarted."

# Convenience: run a one-off sandbox container to execute tests manually
.PHONY: run-sandbox
run-sandbox:
    @echo "Run a sandbox container (example). You must mount repo and artifacts manually."
    @echo "Example:"
    @echo "  docker run --rm --network none -v $(PWD)/some_repo:/workspace:ro -v $(PWD)/artifacts:/sandbox/artifacts:rw $(SANDBOX_IMAGE)"

# -------------------------
# Environment helpers
# -------------------------
# Export environment variables for local dev (optional)
.PHONY: env-dev
env-dev:
    @echo "Export these variables for local development:"
    @echo "export UPLOAD_ROOT=$(PWD)/data/uploads"
    @echo "export ARTIFACTS_ROOT=$(PWD)/data/artifacts"
    @echo "mkdir -p $(PWD)/data/uploads $(PWD)/data/artifacts"

# End of Makefile
