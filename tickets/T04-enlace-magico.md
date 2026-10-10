# T04 — Enlace mágico y correo; fin de contraseñas; webhook crea usuario

Depende de T01. Spec: «Cuenta: enlace mágico», «Pago».

## Alcance
- `servidor/cuentas.py`: `sal` y `hash` pasan a opcionales (migración tolerante;
  los usuarios existentes se conservan). Nueva tabla
  `enlaces(token PK, email, volver, creado, usado)`. Funciones:
  `asegurar_usuario(email)`, `crear_enlace(email, volver)`,
  `consumir_enlace(token)` → email o None (caducidad 15 min, un solo uso),
  `enlaces_ultima_hora(email)` para el límite de 5/hora.
- `servidor/correo.py`: `enviar_enlace(email, url)`. Con `SMTP_HOST` en el
  entorno: SMTP (STARTTLS si puerto 587) con `SMTP_USER/PASS/FROM`. Sin él:
  logging del enlace y devolver `"dev"`. `BASE_URL` para componer la URL
  (fallback `http://127.0.0.1:8000`).
- `servidor/rutas_cuentas.py`: eliminar `/api/cuenta/registro` y
  `/api/cuenta/entrar` con clave. Añadir `POST /api/cuenta/enlace
  {email, volver?}` → 200 `{ok:true, modo:"smtp"|"dev"}` si el correo tiene
  forma válida, 400 si no, 429 si excede 5/hora. `volver` solo rutas relativas
  que empiecen por `/` sin `//` ni esquema; por defecto `/yo`.
  Añadir `GET /entrar/{token}` → consume, fija cookie de sesión (misma
  `_fijar_cookie`), 302 a `volver`; inválido → 302 `/yo?enlace=invalido`.
  `/api/cuenta/salir` y `GET /api/cuenta` se mantienen. `resolver_plan` e
  `identidad` no cambian de firma.
- `servidor/rutas_pagos.py`: en el webhook, antes de `cambiar_plan`, llamar a
  `asegurar_usuario(email)`. El checkout acepta anónimos: si no hay sesión,
  toma `email` del cuerpo (validado) y lo pasa en `custom_data`.
- Actualizar el CLI de `cuentas.py` si crea usuarios con clave (que cree sin).

## Aceptación (tests HTTP)
- `POST /api/cuenta/enlace` crea usuario free y devuelve `modo:"dev"`; el
  enlace capturado del log (caplog) abre sesión (`GET /api/cuenta` trae email).
- Segundo uso del token → redirige a `/yo?enlace=invalido`.
- Token caducado (parchear tiempo) → inválido.
- `volver` malicioso (`//evil`, `http://…`) → se usa `/yo`.
- 6.º enlace en una hora → 429.
- Webhook con firma válida y correo nuevo → usuario creado con plan del evento.
