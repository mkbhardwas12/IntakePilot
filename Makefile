.PHONY: dev api web install test clean

# Zero-dependency dev run: mock LLM + SQLite + local vector index.
dev: install
	@$(MAKE) -j2 api web

api:
	.venv/bin/uvicorn core.api.main:app --host 127.0.0.1 --port 8000 --reload

web:
	cd web && npm run dev

install:
	@test -d .venv || python3 -m venv .venv
	.venv/bin/pip install -q -r requirements-dev.txt
	@test -d web/node_modules || (cd web && npm install)

test:
	.venv/bin/python -m pytest -q

clean:
	rm -rf data/intakepilot.db data/vector_index.json examples/demo-repo/IPR-*.md
