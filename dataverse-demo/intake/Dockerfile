# Build context is the REPO ROOT (see compose.yml), not this folder: the intake imports the
# gema library (src/) and reuses config/agents.yaml + config/dataverse_export.yaml.
FROM python:3.12-slim

WORKDIR /app

COPY dataverse-demo/intake/requirements.txt intake-requirements.txt
RUN pip install --no-cache-dir -r intake-requirements.txt

# gema itself (hatchling build needs pyproject.toml + README.md + src/)
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir .

COPY config/ config/
COPY dataverse-demo/intake/intake_app/ intake_app/

ENV INTAKE_DATA_DIR=/data
VOLUME /data
EXPOSE 8095
# One process only: the rate limiter and the batch lock live in memory.
CMD ["uvicorn", "--factory", "intake_app.main:build_app", "--host", "0.0.0.0", "--port", "8095", "--no-access-log"]
