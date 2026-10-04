# Pinned by digest. Renovate's docker-compose manager does not see a
# Dockerfile FROM, so bump this by hand.
FROM alpine:3.22@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8

# findutils: sync.sh needs GNU find (-printf, -mtime); busybox find lacks it.
RUN apk add --no-cache rsync findutils python3 tzdata

COPY sync.sh trigger.py ui.html apple-touch-icon.png /app/
RUN chmod +x /app/sync.sh

WORKDIR /app
CMD ["python3", "/app/trigger.py"]
