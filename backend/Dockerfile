FROM python:3.11-slim-bookworm

WORKDIR /app

# Install dependencies first (layer-cached unless requirements.txt changes)
COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

# Copy only what the backend needs
COPY backend/ ./backend/
COPY config.yaml .

# Cloud Run sets PORT=8080; local docker-compose defaults to 8001
ENV PORT=8001
EXPOSE 8001

CMD ["sh", "-c", "uvicorn backend.api:app --host 0.0.0.0 --port ${PORT}"]
