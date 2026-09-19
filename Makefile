# TailorTeX: one-command local setup.
#   make setup   create the Python venv and install backend + frontend dependencies
#   make dev     run the backend (:8000) and frontend (:5173) together, with reload
#   make start   build the frontend and serve the whole app from the backend on :8000
#   make test    backend tests, frontend type-check and lint
#   make docker  build and run everything (including TeX Live) in Docker on :8000

PYTHON ?= $(shell command -v python3.12 || command -v python3.11 || command -v python3)
VENV   := .venv
BIN    := $(VENV)/bin
PORT   ?= 8000

.PHONY: setup dev start test docker backend frontend check-tex

setup: $(BIN)/uvicorn frontend/node_modules check-tex
	@test -f .env || cp .env.example .env
	@echo "\nReady. Run 'make dev' and open http://localhost:5173"

$(BIN)/uvicorn: backend/requirements.txt backend/requirements-dev.txt
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -r backend/requirements-dev.txt
	@touch $@

frontend/node_modules: frontend/package.json
	cd frontend && npm install --no-fund --no-audit
	@touch $@

check-tex:
	@if command -v pdflatex >/dev/null 2>&1 || test -x "$$HOME/Library/TinyTeX/bin/universal-darwin/pdflatex" || test -x "$$HOME/.TinyTeX/bin/x86_64-linux/pdflatex" || test -n "$$TAILORTEX_TEX_BIN"; then \
		echo "TeX Live found."; \
	else \
		echo "\n!! No LaTeX found. PDF compiling needs TeX Live. Quickest option (TinyTeX, ~250 MB):"; \
		echo "     curl -sL https://yihui.org/tinytex/install-bin-unix.sh | sh"; \
		echo "   Or run TailorTeX with 'Compile a PDF' turned off to get just the .tex.\n"; \
	fi

backend:
	cd backend && ../$(BIN)/uvicorn tailortex.api.main:app --reload --port $(PORT)

frontend:
	cd frontend && npm run dev

dev: $(BIN)/uvicorn frontend/node_modules
	@echo "Backend  http://localhost:$(PORT)   Frontend  http://localhost:5173"
	@$(MAKE) -j2 --no-print-directory backend frontend

start: $(BIN)/uvicorn frontend/node_modules
	cd frontend && npm run build
	@echo "Open http://localhost:$(PORT)"
	cd backend && ../$(BIN)/uvicorn tailortex.api.main:app --port $(PORT)

test: $(BIN)/uvicorn frontend/node_modules
	cd backend && ../$(BIN)/pytest -q
	cd frontend && npx tsc -b && npx oxlint src

docker:
	@test -f .env || cp .env.example .env
	docker compose up --build
