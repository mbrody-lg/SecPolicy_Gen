# Local/development Flask image. Not a production runtime contract.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/validator-agent
ENV FLASK_RUN_DEBUG=0


RUN apt-get update && apt-get install -y gcc

WORKDIR /validator-agent

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

CMD ["sh", "-c", "if [ \"$FLASK_RUN_DEBUG\" = \"1\" ] || [ \"$FLASK_RUN_DEBUG\" = \"true\" ]; then exec flask run --host=0.0.0.0 --port=5000 --debug; fi; exec flask run --host=0.0.0.0 --port=5000"]
