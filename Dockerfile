FROM python:3.13-slim

WORKDIR /app
RUN apt-get update && apt-get -y install gdal-bin && rm -rf /var/lib/apt/lists/*
RUN pip3 install uv
COPY pyproject.toml pyproject.toml
# https://stackoverflow.com/a/54763270
COPY gerrydb_meta gerrydb_meta
RUN uv pip install --system --no-cache .
COPY serve.sh serve.sh
RUN chmod +x serve.sh

CMD ["/app/serve.sh"]
