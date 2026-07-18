FROM python:3.11-slim

WORKDIR /opt/specgate

COPY pyproject.toml README.md /opt/specgate/
COPY src /opt/specgate/src
COPY examples /opt/specgate/examples

RUN python -m pip install --no-cache-dir -e . \
    && mkdir -p /workspace /data/specgate-web

ENV SPECGATE_WEB_DATA=/data/specgate-web

WORKDIR /workspace

ENTRYPOINT ["specgate"]
CMD ["--help"]
