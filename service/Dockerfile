# built from repo root:  docker build -f service/Dockerfile -t jingo:local .
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY engine /tmp/engine
RUN pip install --no-cache-dir /tmp/engine \
    && rm -rf /tmp/engine

COPY service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY service/app ./app

ENV JINGO_RECORDS_DIR=/opt/libretexts/jingo/records
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
