# Pinned by digest. Renovate's docker-compose manager does not see a
# Dockerfile FROM, so bump this by hand.
FROM alpine:3.22@sha256:5291449c3df73caf6ed85e649dec1b9e818b39a5d8c871e97afc13e9cd5e8fa8
RUN apk add --no-cache python3 tzdata
COPY prune.py /app/
WORKDIR /app
CMD ["python3", "/app/prune.py"]
