FROM python:3.12-slim
WORKDIR /app
# Chromium de Playwright para leer sitios hechos con JavaScript (ver SABIO_RENDER_JS en README.md)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY requirements.txt .
# libatomic1: el programa interno de Playwright (desde la 1.65) la necesita para arrancar, y la imagen
# slim no la trae; sin ella "playwright install" falla antes de poder instalar sus propias dependencias
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
    && pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*
COPY . .
RUN python scripts/demo_data.py
ENV SABIO_DB=/data/sabio.db SABIO_DEMO=1 PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
