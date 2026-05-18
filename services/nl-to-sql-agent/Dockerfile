FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/shared

WORKDIR /app
COPY services/nl-to-sql-agent/requirements.txt ./requirements.txt
RUN pip install --timeout 120 --no-cache-dir -r requirements.txt
COPY shared ./shared
COPY skills ./skills
COPY services/nl-to-sql-agent/app ./app
CMD ["python", "-m", "app.main"]
