# FleetPulse developer shortcuts. `make help` lists them.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PYTHON ?= python3.12
IMAGE ?= fleetpulse:local

.PHONY: help install test lint coverage version up down logs api-smoke k8s-render tf-check clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Create the virtualenv and install everything
	$(PYTHON) -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt -r ci_doctor/requirements.txt

test: ## Run pytest (includes the bash version-script suite) with the coverage gate
	$(PYTHON) -m pytest

lint: ## flake8 across source, tests, simulator and ci_doctor
	$(PYTHON) -m flake8 src tests simulator ci_doctor

coverage: ## Coverage report with missing lines
	$(PYTHON) -m pytest --cov=fleetpulse --cov-report=term-missing --cov-report=html

version: ## Print the next SemVer from Conventional Commits
	@bash scripts/next_version.sh

up: ## docker compose up --build (API + Prometheus + Grafana + simulator)
	docker compose up --build

down: ## Stop the stack and remove volumes
	docker compose down -v

logs: ## Tail the API logs
	docker compose logs -f api

api-smoke: ## Post one frame and print the fleet summary
	curl -fsS -X POST localhost:8000/v1/telemetry \
	  -H 'content-type: application/json' \
	  -d '{"drone_id":"drone-01","battery_pct":42.5,"altitude_m":120,"speed_mps":12.5,"lat":12.97,"lon":77.59}'
	@echo
	curl -fsS localhost:8000/v1/fleet/summary

k8s-render: ## Render both Kustomize overlays
	kubectl kustomize k8s/overlays/local
	kubectl kustomize k8s/overlays/production

tf-check: ## Format check and validate the Terraform
	cd infra/terraform && terraform fmt -check -recursive && terraform init -backend=false && terraform validate

clean: ## Remove caches and coverage output
	rm -rf .pytest_cache .coverage htmlcov apps/*/.pytest_cache 2>/dev/null || true
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
