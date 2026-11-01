FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /workspace
COPY engine/ /workspace/engine/
COPY production/backup_worker.py /workspace/production/backup_worker.py
RUN python -m pip install --no-cache-dir /workspace/engine
RUN groupadd --gid 10001 aiapp && useradd --uid 10001 --gid aiapp --no-create-home aiapp \
 && mkdir -p /workspace/app /workspace/data /workspace/config /workspace/backups \
 && chown -R aiapp:aiapp /workspace/app /workspace/data /workspace/config /workspace/backups
USER 10001:10001
CMD ["python", "-m", "ai_app_server.cli", "run", "/workspace/app/app.py", "--data-dir", "/workspace/data", "--host", "127.0.0.1", "--port", "8501", "--mode", "production"]
