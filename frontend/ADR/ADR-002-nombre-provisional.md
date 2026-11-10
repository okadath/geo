# ADR-002 — Nombre y dominio: «Pergamundi»

**Estado:** aceptada · 2026-07-17 (provisional «Mundaria») → 2026-11-10 (definitivo)

## Contexto

`PLATAFORMA.md` §1.1 dejaba el nombre y dominio como pendiente del dueño. Se
usó «Mundaria» como nombre de trabajo mientras se construían landing y
navegación. Al buscar dominio, `mundaria.com` (y todas las variantes obvias
de mundo/tectónica/battlemap) estaban tomadas.

## Decisión

El producto se llama **Pergamundi** (pergamino + mundo), con el tagline
**«Del planeta al encuentro»**. Dominio registrado: **pergamundi.com**
(Squarespace, 2026-11-10).

Criterios que cumple: pronunciable en español e inglés (el marketing apunta a
r/battlemaps, anglófono), evoca el mapa de pergamino que es el gancho viral
(`NEGOCIO.md` §10.3) y el mundo entero detrás, y no comparte raíz con
Inkarnate, Wonderdraft, Dungeondraft ni Azgaar.

El nombre vive en un solo lugar del código (`assets/js/marca.js`); el resto
(títulos de página, correos, `Caddyfile.ejemplo`, rutas de despliegue) se
actualizó en el mismo commit.

## Consecuencias

- Pendiente: verificar marca registrada (USPTO e IMPI) antes del lanzamiento
  público; un .com libre no garantiza marca libre.
- `DESPLIEGUE.md` usa `/opt/pergamundi` y el usuario `pergamundi`; el
  remitente de correo por defecto es `no-responder@pergamundi.com`.
