FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# config.py, cache, and logs are mounted at runtime — never baked in
VOLUME ["/app/config.py", "/app/lastfm_similar_cache.json", "/app/log"]

CMD ["python3", "DiscoveryLastFM.py", "--daemon"]
