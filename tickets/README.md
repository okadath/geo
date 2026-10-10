# Tickets — rutas y pantallas de Mundaria

Derivados de `../ESPECIFICACION_RUTAS.md`. Cada ticket es autocontenido para un
agente: alcance, criterios de aceptación, dependencias. Las decisiones de
producto NO se renegocian en el ticket; están en la especificación.

Reglas comunes a todos:
- Lógica (gating, resolución de mundo, lugares, cuentas) SIEMPRE en `servidor/`
  (Python). El front (`frontend/`) solo presenta.
- No tocar estilos: reutilizar clases de `tokens.css`/`base.css`; una hoja
  nueva por página solo para layout imprescindible.
- No romper `/lab`, `/regiones`, `/api/*` existentes ni los módulos `_srv`.
- Correr `python -m pytest -q` antes de cerrar; añadir pruebas al seam HTTP.
- Comentarios y textos en español, como el resto del repo.

| # | Ticket | Depende de | Paralelo con |
|---|---|---|---|
| T01 | Infraestructura de pruebas HTTP | — | — |
| T02 | Endpoint de mundo, públicos, mundo del día, visibilidad | T01 | T03 T04 T05 |
| T03 | Lugares destacados por reglas | T01 | T02 T04 T05 |
| T04 | Enlace mágico y correo; fin de contraseñas; webhook crea usuario | T01 | T02 T03 T05 |
| T05 | Guardados (mundos y battlemaps) | T01 | T02 T03 T04 |
| T06 | Rutas de páginas nuevas, redirecciones, OG de la ficha | T02 T03 T04 T05 | — |
| T07 | nav.js con migas de pan; api.js con endpoints nuevos | T06 | — |
| T08 | Portada `/` y ficha `/w/<sello>` | T07 | T09 T10 |
| T09 | Visor `/w/<sello>/mapa` y battlemap `/w/<sello>/<x>,<y>` | T07 | T08 T10 |
| T10 | `/nuevo` y `/yo` | T07 | T08 T09 |
| T11 | Juego en `/w/<sello>/jugar` | T06 | T08 T09 T10 |
| T12 | ADR-010, README, limpieza | T08 T09 T10 T11 | — |
