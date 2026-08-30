.PHONY: dev api web install hooks check-attribution test clean improve

# Zero-dependency dev run: mock LLM + SQLite + local vector index.
dev: install
	@$(MAKE) -j2 api web

api:
	.venv/bin/uvicorn core.api.main:app --host 127.0.0.1 --port 8000 --reload

web:
	cd web && npm run dev

install: hooks
	@test -d .venv || python3 -m venv .venv
	.venv/bin/pip install -q -r requirements-dev.txt
	@test -d web/node_modules || (cd web && npm install)

hooks:
	git config core.hooksPath .githooks

check-attribution:
	python3 scripts/check_agent_attribution.py --all

test:
	.venv/bin/python -m pytest -q

clean:
	rm -rf data/intakepilot.db data/vector_index.json examples/demo-repo/IPR-*.md

# One improvement pass: ship the MANAS outbox (+health), harvest analyst/
# glossary proposals, replay corrections as evals. Cron this.
improve:
	.venv/bin/python -m scripts.improve
