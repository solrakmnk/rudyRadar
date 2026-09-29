up:
	docker compose up --build
down:
	docker compose down
logs:
	docker compose logs -f app
migrate:
	docker compose exec app alembic upgrade head
test:
	docker compose exec app pytest
