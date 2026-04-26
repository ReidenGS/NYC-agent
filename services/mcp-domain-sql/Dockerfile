FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/shared

WORKDIR /app
COPY services/mcp-domain-sql/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY shared ./shared
COPY services/mcp-domain-sql/app ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8022"]
