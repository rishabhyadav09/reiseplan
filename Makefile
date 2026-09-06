.PHONY: dev test lint up down smoke

dev:
	cd backend && uvicorn app.main:app --reload --port 8000

test:
	cd backend && python -m pytest -q

lint:
	cd backend && ruff check app tests

up:
	docker compose up --build

down:
	docker compose down -v

smoke:
	curl -s "http://localhost:8000/api/plan?origin=Dortmund&destination=M%C3%BCnchen&preset=balanced" | python -m json.tool | head -40
