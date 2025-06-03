# Dockerfile per Flask amb entorn de desenvolupament
FROM python:3.11-slim

# Variables d’entorn
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/validator-agent


# Instal·lació de dependències del sistema
RUN apt-get update && apt-get install -y gcc

# Directori de treball
WORKDIR /validator-agent

# Copiem els arxius
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Comandament per executar Flask
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000", "--debug"]

