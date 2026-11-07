FROM docker:cli AS dockercli

FROM python:3.12-slim

# ca-certificates is needed for HTTPS requests to the Telegram API.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The Docker CLI talks to the host daemon through the mounted socket.
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONUNBUFFERED=1

CMD ["python", "src/bot.py"]
