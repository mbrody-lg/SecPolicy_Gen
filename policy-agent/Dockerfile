# Local/development Flask image. Not a production runtime contract.
FROM python:3.11-slim

ARG PIP_VERSION=26.2.1
ARG TORCH_VERSION=2.14.0+cpu
ARG TORCH_CPU_INDEX=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/policy-agent
ENV PIP_NO_CACHE_DIR=1
ENV FLASK_RUN_DEBUG=0


RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /policy-agent

COPY requirements.txt constraints-py311.txt ./
RUN python -m pip install --upgrade "pip==${PIP_VERSION}" \
    && python -m pip install --index-url "${TORCH_CPU_INDEX}" "torch==${TORCH_VERSION}" \
    && python -m pip install -c constraints-py311.txt -r requirements.txt \
    && python -m pip check

COPY . .

CMD ["sh", "-c", "if [ \"$FLASK_RUN_DEBUG\" = \"1\" ] || [ \"$FLASK_RUN_DEBUG\" = \"true\" ]; then exec flask run --host=0.0.0.0 --port=5000 --debug; fi; exec flask run --host=0.0.0.0 --port=5000"]
