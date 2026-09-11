# All commands use an isolated development environment, never tracked burry_env or local .venv.
# Pinned local toolchains avoid accidentally using tracked burry_env or a developer's .venv.
PYTHON := .dev-venv/bin/python
PIP := .dev-venv/bin/pip
NODE_BIN := .tools/node/bin
NPM := $(NODE_BIN)/npm
NPX := $(NODE_BIN)/npx

.PHONY: setup dev migrate test lint typecheck static security restore-test check browser-setup browser-install browser-test mcp-smoke acceptance live live-smoke release release-check backup restore clean

setup:
	python3 -m venv .dev-venv
	$(PYTHON) -m pip install --disable-pip-version-check pip==25.2
	$(PIP) install --disable-pip-version-check --requirement requirements.lock
	$(PIP) install --disable-pip-version-check --no-build-isolation --no-deps --editable .

dev:
	$(PYTHON) -m stock_probs.cli serve --host 127.0.0.1 --port 8000

migrate:
	$(PYTHON) -m stock_probs.cli migrate

test:
	mkdir -p test-results/python
	$(PYTHON) -m pytest -m "not live" --cov=stock_probs --cov-report=term-missing --cov-fail-under=85 --junitxml=test-results/python/junit.xml

lint:
	$(PYTHON) -m ruff check src tests scripts

typecheck:
	# M05 operational modules are the first strict typing boundary; imported app layers stay separate.
	$(PYTHON) -m mypy src/stock_probs/backup.py src/stock_probs/cli.py

static:
	$(PYTHON) -m compileall -q src tests scripts
	bash -n scripts/*.sh
	$(PYTHON) scripts/comment_audit.py

security:
	# Ruff's S rules fail here; the non-live suite above supplies host/origin/path regressions.
	$(PYTHON) -m ruff check --select S --ignore S101 src tests scripts

restore-test:
	$(PYTHON) -m pytest tests/test_repository_backup.py tests/test_backup_cli.py -q

check: lint typecheck static test security restore-test

browser-setup:
	./scripts/install-node-arm64.sh
	PATH="$(CURDIR)/$(NODE_BIN):$$PATH" $(NPM) --prefix tools/browser ci

browser-install: browser-setup
	# Playwright's maintained dependency list is architecture-aware on supported Linux hosts.
	PATH="$(CURDIR)/$(NODE_BIN):$$PATH" $(NPX) --prefix tools/browser playwright install --with-deps chromium

browser-test: browser-setup
	# Allocate a free loopback port unless QA pins one; never reuse a stale test server.
	PORT="$${STOCK_PROBS_BROWSER_PORT:-$$($(PYTHON) -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')}"; \
	PATH="$(CURDIR)/$(NODE_BIN):$$PATH" STOCK_PROBS_BROWSER_PORT="$$PORT" $(NPM) --prefix tools/browser test

mcp-smoke: browser-setup
	# The smoke client initializes MCP, lists tools, and opens an isolated Chromium context.
	PATH="$(CURDIR)/$(NODE_BIN):$$PATH" $(NODE_BIN)/node tools/browser/mcp-smoke.js

acceptance: check browser-test

live-smoke:
	$(PYTHON) -m pytest -m live -v

live: live-smoke

release-check: acceptance
	$(PYTHON) -m stock_probs.cli migrate
	$(PYTHON) -m pytest tests/test_backup_cli.py -q

release: release-check

backup:
	$(PYTHON) -m stock_probs.cli backup

# Usage: make restore BACKUP=stock-probs-YYYYMMDDTHHMMSSZ.spbackup PROMOTE=--promote
restore:
	$(PYTHON) -m stock_probs.cli restore "$(BACKUP)" $(PROMOTE)

clean:
	rm -rf .pytest_cache .ruff_cache test-results playwright-report .playwright-mcp tools/browser/test-results tools/browser/playwright-report
