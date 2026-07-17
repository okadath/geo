# ADR-002 — Nombre de trabajo: «Mundaria»

**Estado:** aceptada (provisional) · 2026-07-17

## Contexto

`PLATAFORMA.md` §1.1 deja el nombre y dominio como pendiente del dueño, pero la
landing y la navegación necesitan una marca hoy. Nada más depende del nombre.

## Decisión

Se usa **Mundaria** como nombre de trabajo, con el tagline
**«Del planeta al encuentro»**. Criterios: pronunciable en español e inglés
(el marketing apunta a r/battlemaps, anglófono), evoca «mundo», sin colisión
obvia en el nicho (Inkarnate/Wonderdraft/Dungeondraft/Azgaar).

El nombre vive en un solo lugar del código (`assets/js/marca.js`) para que
cambiarlo sea un solo edit cuando el dueño registre dominio/marca.

## Consecuencias

- Antes del lanzamiento real hay que verificar dominio y marca registrada;
  si cambia, el costo es un string y el logo SVG.
