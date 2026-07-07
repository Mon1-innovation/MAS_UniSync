FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY mas_unisync_server ./mas_unisync_server
COPY scripts ./scripts

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "scripts/run_dev_server.py", "--host", "0.0.0.0", "--port", "8000"]
