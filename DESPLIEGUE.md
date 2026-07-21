# Despliegue

Cómo correr Mundaria en tu máquina y en producción. El servidor es FastAPI +
Uvicorn (paquete `servidor/`, app en `servidor.app:app`); `web.py` es solo un
lanzador delgado. Referencia de infraestructura: **PLATAFORMA.md §2**.

---

## 1. Local (desarrollo)

Requisitos: Python 3.10+ y las dependencias de `requirements.txt`
(numpy, Pillow, fastapi, uvicorn).

```bash
# crear el entorno una vez
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# arrancar (python3 web.py se re-ejecuta solo dentro de .venv)
python3 web.py                 # http://127.0.0.1:8000
python3 web.py -p 8125         # otro puerto
python3 web.py --sin-recarga   # sin autorecarga al editar .py
```

- Por defecto escucha **solo en 127.0.0.1** (no expuesto a la red).
- La autorecarga la hace uvicorn vigilando los `*.py`; `--sin-recarga` la apaga.
- Rutas útiles: `/` landing, `/estudio`, `/cuenta` (mi cuenta), `/lab` (panel
  científico), `/api/corridas`, `/api/pagos/config`.

---

## 2. Producción (VPS + Caddy + uvicorn)

Arquitectura: **Caddy** termina HTTPS de cara a internet y hace de reverse proxy
hacia **uvicorn**, que escucha solo en `127.0.0.1:8000`. La app nunca se expone
directa (PLATAFORMA.md §2).

### 2.0 De cero por SSH (VPS Ubuntu/Debian recién creado)

```bash
ssh root@IP-DEL-SERVER

# 1. dependencias del sistema
apt update && apt install -y python3-venv git caddy sqlite3

# 2. usuario sin privilegios para la app
adduser --system --group --home /opt/mundaria mundaria

# 3. el código: clonar (o subirlo con rsync desde tu máquina:
#    rsync -av --exclude .venv --exclude salidas --exclude cuentas.db \
#          --exclude __pycache__ ./ mundaria@IP:/opt/mundaria/)
sudo -u mundaria git clone <URL-DEL-REPO> /opt/mundaria

# 4. entorno de python (el .venv NO viaja: se recrea aquí)
cd /opt/mundaria
sudo -u mundaria python3 -m venv .venv
sudo -u mundaria .venv/bin/pip install -r requirements.txt

# 5. mundos: subir las corridas que quieras servir a salidas/ (rsync) y
#    listar las publicas del free tier en publicos.json, p. ej.:
#    echo '["20260710-203146"]' > publicos.json
#    (sin el archivo, TODOS los mundos son publicos: modo desarrollo)

# 6. servicio + proxy (ver 2.1 y 2.2)

# 7. firewall: solo ssh y web
ufw allow OpenSSH && ufw allow 80,443/tcp && ufw enable
```

El DNS del dominio debe apuntar a la IP del VPS **antes** de arrancar Caddy
(lo necesita para emitir el certificado TLS).

### 2.1 App (uvicorn)

Un solo worker: el estado de los jobs de render vive en memoria del proceso
(diccionario `jobs` en `servidor/corridas.py`), así que **no** escales con
`--workers > 1` sin antes externalizar ese estado.

```bash
.venv/bin/uvicorn servidor.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Ejemplo de unidad systemd (`/etc/systemd/system/mundaria.service`):

```ini
[Unit]
Description=Mundaria (uvicorn)
After=network.target

[Service]
User=mundaria
WorkingDirectory=/opt/mundaria
Environment=PYTHONUNBUFFERED=1
# Variables de la pasarela Paddle (FUTURAS — hoy vacías = modo beta, sin cobro):
#   PADDLE_TOKEN         habilita POST /api/pagos/checkout (sin él -> 503 beta)
#   PADDLE_WEBHOOK_SECRET verifica la firma del webhook (sin él -> 503 beta)
# Mientras no existan, la pasarela responde honestamente "modo beta" (ADR-007).
# Environment=PADDLE_TOKEN=xxxxx
# Environment=PADDLE_WEBHOOK_SECRET=xxxxx
ExecStart=/opt/mundaria/.venv/bin/uvicorn servidor.app:app --host 127.0.0.1 --port 8000 --workers 1
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now mundaria
```

### 2.2 Reverse proxy (Caddy)

Copia `Caddyfile.ejemplo` a `/etc/caddy/Caddyfile`, cambia el dominio y
recarga. Caddy obtiene y renueva el certificado TLS automáticamente.

```bash
sudo cp Caddyfile.ejemplo /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

---

## 3. Pasarela de pagos (Paddle) — cuando se conecte

Hoy la pasarela está **lista en código pero apagada** (ADR-007: nunca un
checkout falso). El comportamiento depende de dos variables de entorno:

| Variable                | Falta (hoy)                          | Presente (futuro) |
|-------------------------|--------------------------------------|-------------------|
| `PADDLE_TOKEN`          | `POST /api/pagos/checkout` → 503 beta | inicia el checkout |
| `PADDLE_WEBHOOK_SECRET` | `POST /api/pagos/webhook` → 503 beta  | verifica la firma y actualiza el plan |

El webhook valida la firma de Paddle (`Paddle-Signature`: HMAC-SHA256 de
`ts:cuerpo` con el secreto, con ventana anti-replay de 5 min) y aplica los
eventos `subscription.created/updated/canceled` sobre `servidor.cuentas`.

---

## 4. Copias de seguridad

Dos rutas guardan datos que **no** están en git (ver `.gitignore`):

- `cuentas.db` — usuarios, sesiones y planes (SQLite). **Crítico**: respáldalo
  a menudo; su pérdida cierra la sesión de todos y borra los planes.
- `salidas/` — todas las corridas y renders generados. Pesado pero
  regenerable; respáldalo según convenga.
- `publicos.json` — lista de mundos públicos (si no existe, todos son públicos:
  modo desarrollo).

Ejemplo de respaldo diario de la base de cuentas:

```bash
sqlite3 /opt/mundaria/cuentas.db ".backup '/var/backups/mundaria/cuentas-$(date +%F).db'"
```

---

## 5. Verificación rápida tras desplegar

```bash
curl -s https://tu-dominio/api/corridas | head -c 200      # JSON de corridas
curl -s https://tu-dominio/api/pagos/config                # {"activo":false,...}
curl -si https://tu-dominio/cuenta | head -n 1             # 200 (página mi cuenta)
```
