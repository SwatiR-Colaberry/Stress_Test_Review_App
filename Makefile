.PHONY: install test scan-secrets run

install:
	pip install -r requirements-dev.txt

test:
	pytest

scan-secrets:
	python3 backend/scripts/scan_for_credentials.py

run:
	uvicorn app.main:app --app-dir backend --reload
