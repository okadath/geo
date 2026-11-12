# ADR-002 — Nombre y dominio: «Pangeira»

**Estado:** aceptada · 2026-07-17 (provisional «Mundaria») → 2026-11-10 («Pergamundi») → 2026-11-12 (definitivo, «Pangeira»)

## Contexto

`PLATAFORMA.md` §1.1 dejaba el nombre y dominio como pendiente del dueño. Se
usó «Mundaria» como nombre de trabajo mientras se construían landing y
navegación. Al buscar dominio, `mundaria.com` (y todas las variantes obvias
de mundo/tectónica/battlemap) estaban tomadas. El 2026-11-10 se eligió
«Pergamundi» (pergamino + mundo) y se registró `pergamundi.com`; dos días
después se cambió a «Pangeira», uno de los `.com` libres de esa misma búsqueda.

## Decisión

El producto se llama **Pangeira** (de Pangea, el supercontinente), con el
tagline **«Del planeta al encuentro»**. Dominio: **pangeira.com**, en
producción desde el 2026-11-12.

Criterios que cumple: pronunciable en español e inglés (el marketing apunta a
r/battlemaps, anglófono), evoca la tectónica que es el motor del producto y
el mundo entero detrás, y no comparte raíz con
Inkarnate, Wonderdraft, Dungeondraft ni Azgaar.

El nombre vive en un solo lugar del código (`assets/js/marca.js`); el resto
(títulos de página, correos, `Caddyfile.ejemplo`, rutas de despliegue) se
actualizó en el mismo commit.

## Consecuencias

- Pendiente: verificar marca registrada (USPTO e IMPI) antes del lanzamiento
  público; un .com libre no garantiza marca libre.
- `DESPLIEGUE.md` usa `/opt/pangeira` y el usuario `pangeira`; el
  remitente de correo por defecto es `no-responder@pangeira.com`.
