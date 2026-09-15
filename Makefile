# NeoStay -- the common commands. Run `make` on its own to list them.
#
#   make run        NeoStay on this computer, with sign-in, at http://127.0.0.1:8000
#   make up         NeoStay in a container, as on a hospital server (docs/DEPLOYMENT.md)

SHELL := /bin/bash
.DEFAULT_GOAL := help

VENV := .venv
PY   := $(VENV)/bin/python
PORT := 8000
USERS_FILE := instance/access/users.json

.PHONY: help setup setup-dev run test data site site-serve \
        user-add user-remove user-list user-export \
        up https down logs docker-user-add docker-user-list smoke

help: ## Show this help
	@echo ""
	@echo "  NeoStay"
	@echo ""
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "    \033[36m%-17s\033[0m %s\n", $$1, $$2}'
	@echo ""

## ------------------------------------------------------------ this computer ----

setup: $(VENV)/.installed ## Create .venv with the server's dependencies

$(VENV)/.installed: backend/requirements.txt
	@python3 -m venv $(VENV)
	@$(VENV)/bin/pip install --quiet --upgrade pip
	@$(VENV)/bin/pip install --quiet -r backend/requirements.txt
	@touch $@

setup-dev: $(VENV)/.installed-dev ## Also install the test and build tools

$(VENV)/.installed-dev: requirements-dev.txt $(VENV)/.installed
	@$(VENV)/bin/pip install --quiet -r requirements-dev.txt
	@touch $@

run: setup ## Start NeoStay with sign-in on http://127.0.0.1:8000
	@test -s $(USERS_FILE) || echo "No accounts yet. Create one first:  make user-add EMAIL=you@hospital.org"
	@cd backend && NEOSTAY_ENV=$${NEOSTAY_ENV:-development} ../$(VENV)/bin/uvicorn app.main:app \
		--host 127.0.0.1 --port $(PORT) $(if $(wildcard .env),--env-file ../.env,)

test: setup-dev ## Run every test, including browser/Python engine parity
	@$(PY) -m pytest

data: setup ## Rebuild frontend/data/ from the CSVs in datasets/ and generated_data/
	@$(PY) scripts/build_frontend_data.py

site: setup-dev ## Build the GitHub Pages site into site/ (sealed for local accounts, if any)
	@$(PY) scripts/build_pages_site.py --out site $(if $(wildcard $(USERS_FILE)),--users-file $(USERS_FILE),)

site-serve: site ## Build the Pages site and preview it on http://127.0.0.1:8001
	@cd site && ../$(PY) -m http.server 8001 --bind 127.0.0.1

## --------------------------------------------------------------- accounts ----
# Passwords are typed at a hidden prompt: never in shell history, Git, or any
# file other than the hashed users file in instance/.

user-add: setup ## Create an account or set a new password (EMAIL=... NAME="...")
	@test -n "$(EMAIL)" || { echo 'Usage: make user-add EMAIL=someone@hospital.org NAME="Full Name"'; exit 1; }
	@cd backend && ../$(PY) -m app.accounts add "$(EMAIL)" $(if $(NAME),--name "$(NAME)",)

user-remove: setup ## Remove an account (EMAIL=...)
	@test -n "$(EMAIL)" || { echo "Usage: make user-remove EMAIL=someone@hospital.org"; exit 1; }
	@cd backend && ../$(PY) -m app.accounts remove "$(EMAIL)"

user-list: setup ## List who can sign in
	@cd backend && ../$(PY) -m app.accounts list

user-export: setup ## Print the accounts for the NEOSTAY_USERS_JSON GitHub secret
	@cd backend && ../$(PY) -m app.accounts export

## ------------------------------------------------------------ the server ----

up: ## Build and start the server container (NeoStay on 127.0.0.1:8000)
	@docker compose up -d --build

https: ## Build and start the container with the bundled HTTPS proxy
	@docker compose --profile https up -d --build

down: ## Stop the containers (accounts are kept)
	@docker compose --profile https down

logs: ## Follow the container logs
	@docker compose --profile https logs -f

docker-user-add: ## Create an account on the running server (EMAIL=... NAME="...")
	@test -n "$(EMAIL)" || { echo 'Usage: make docker-user-add EMAIL=someone@hospital.org NAME="Full Name"'; exit 1; }
	@docker compose exec app python -m app.accounts add "$(EMAIL)" $(if $(NAME),--name "$(NAME)",)

docker-user-list: ## List who can sign in on the running server
	@docker compose exec app python -m app.accounts list

smoke: ## Check a running server end to end (URL=... EMAIL=...; asks for the password)
	@test -n "$(URL)" -a -n "$(EMAIL)" || { echo "Usage: make smoke URL=https://neostay.hospital.local EMAIL=someone@hospital.org"; exit 1; }
	@read -rsp "Password for $(EMAIL): " password && echo && \
		NEOSTAY_SMOKE_PASSWORD="$$password" scripts/smoke_test.sh "$(URL)" "$(EMAIL)"
