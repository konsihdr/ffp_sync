# Verwende das offizielle Python-Image als Basis
FROM python:3.11-slim

# Setze das Arbeitsverzeichnis im Container
WORKDIR /app

# Kopiere die Abhängigkeiten und Skripte in das Arbeitsverzeichnis
COPY sync_script.py .
COPY sync_posts_apify.py .
COPY requirements.txt .
COPY .env .

# Installiere die Abhängigkeiten
RUN pip install --no-cache-dir -r requirements.txt

# Starte das Sync-Skript mit unbuffered output
CMD ["python3", "-u", "sync_script.py"]