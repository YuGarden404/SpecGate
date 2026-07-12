FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src
COPY examples /app/examples

RUN python -m pip install --no-cache-dir -e .

ENV SPECGATE_WEB_DATA=/data/specgate-web

RUN mkdir -p /data/specgate-web

VOLUME ["/data/specgate-web"]
EXPOSE 8000

CMD ["specgate-web", "--host", "0.0.0.0", "--port", "8000"]
