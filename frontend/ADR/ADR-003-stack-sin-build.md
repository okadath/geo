# ADR-003 — Stack del front: vanilla ES modules, sin framework ni build

**Estado:** aceptada · 2026-07-17

## Contexto

El back es `http.server` de la biblioteca estándar sirviendo HTML vanilla; el
proyecto es de un solo desarrollador y todo el código existente (juego,
fantasía, batalla) ya es vanilla JS + canvas y funciona bien. La API no tiene
CORS: el front debe servirse desde el mismo origen (`127.0.0.1:8000`).

Alternativas evaluadas: (a) SPA con React/Vite — exige toolchain Node, build,
y un proxy de dev contra un back que no lo necesita; (b) vanilla con ES
modules y CSS moderno — cero dependencias, se sirve como archivos estáticos.

## Decisión

**(b) Vanilla.** El front nuevo vive en `frontend/` como HTML + CSS + ES
modules, servido estáticamente por `web.py`. Compartición de código por
módulos JS (`assets/js/api.js` cliente de API, `assets/js/nav.js` cabecera
inyectada) y un sistema de diseño en CSS custom properties
(`assets/css/tokens.css`).

## Consecuencias

- Cero pasos de build/instalación: `python3 web.py` y listo — coherente con el
  flujo del dueño y con el despliegue previsto (Caddy + estáticos).
- Sin CORS ni configuración de orígenes: mismo host que la API.
- La disciplina de componentes es por convención (clases CSS documentadas en
  `tokens.css`/`base.css`), no impuesta por framework; aceptable a esta escala.
- Si el producto crece a necesitar estado complejo compartido, migrar a un
  framework será una reescritura de presentación, no de lógica (la lógica está
  en el servidor).
