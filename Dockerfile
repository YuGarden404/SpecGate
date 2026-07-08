FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md /app/
COPY src /app/src
COPY examples /app/examples

ENV PYTHONPATH=/app/src

CMD ["python", "-m", "specgate.cli", "run-mock-demo", "examples/knowledge_nav"]
