FROM python:3.14.2-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    libgl1 \
    libglib2.0-0 \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*


COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x /app/docker/start-web.sh
RUN chmod +x /app/docker/start-worker.sh

EXPOSE 8007

CMD ["/app/docker/start-web.sh"]
