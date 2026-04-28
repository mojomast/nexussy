.PHONY: install test lint smoke pi-smoke tui clean

install:
	pip install -e "core/[dev]"
	cd tui && bun install

test: lint
	cd core && python3 -m pytest tests/ -v --tb=short
	python3 -m pytest -q web/tests/
	cd tui && bun test

lint:
	ruff check core/nexussy/
	cd tui && bun run typecheck

smoke:
	bash ops_tests.sh

pi-smoke:
	@echo '{"jsonrpc":"2.0","id":"t1","method":"agent.run","params":{"task":"list files","context":""}}' | \
	timeout 15 python3 -m nexussy.swarm.local_pi_worker

tui:
	cd tui && bun test

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf core/dist core/build core/*.egg-info
