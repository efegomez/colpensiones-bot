FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium ya viene instalado en esta imagen base
RUN python -m playwright install chromium

COPY . .

EXPOSE 5000

CMD gunicorn app:app --bind 0.0.0.0:${PORT:-5000} --timeout 60 --workers 1
