# Imagen de produccion de Pangeira (FastAPI + uvicorn) para Dokploy.
# Datos persistentes (montar como volumenes):
#   /app/salidas  -> corridas/mundos (batalla/fantasia/juego la resuelven desde BASE)
#   /data         -> cuentas.db y publicos.json (TECTO_DB / TECTO_PUBLICOS)
FROM python:3.14-slim

# fuentes que usan batalla_srv.py y fantasia_srv.py para los rotulos
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-liberation fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TECTO_DB=/data/cuentas.db \
    TECTO_PUBLICOS=/data/publicos.json

RUN mkdir -p /data /app/salidas
VOLUME ["/data", "/app/salidas"]
EXPOSE 8000

# Un solo worker: el estado de los jobs vive en memoria (DESPLIEGUE.md 2.1).
# El proxy (Traefik de Dokploy) va delante: se confia en sus cabeceras.
CMD ["uvicorn", "servidor.app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
