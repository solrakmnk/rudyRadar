FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app
RUN addgroup --system radar && adduser --system --ingroup radar radar
COPY pyproject.toml ./
RUN pip install --no-cache-dir .[dev]
COPY --chown=radar:radar . .
RUN chown -R radar:radar /app
USER radar
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
