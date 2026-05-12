FROM python:3.12-slim

# Non-root user for security
RUN useradd --create-home appuser

WORKDIR /app

# Install dependencies first (layer-cached separately from app code)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Persistent data directory (mount a volume here to survive container restarts)
RUN mkdir -p /app/data && chown appuser:appuser /app/data

USER appuser

EXPOSE 5000

# Run database migrations then start the production server
CMD flask db upgrade && \
    gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:application
