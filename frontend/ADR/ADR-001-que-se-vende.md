# ADR-001 — Qué se vende y qué prioridad tiene cada pieza

**Estado:** aceptada · 2026-07-17

## Contexto

El repositorio tiene cuatro superficies funcionales (`/` generador científico,
`/fantasia`, `/batalla`, `/juego`) como pruebas de concepto sin orden estético
ni flujo comercial. `NEGOCIO.md` §8–10 ya contiene el análisis de mercado
(comparables: Czepeku ~$80k/mes en battlemaps, Inkarnate $7.99/mes,
Dungeondraft $19.99, Azgaar gratis) y una decisión: el producto vendible es la
herramienta creativa, no el juego ni los mapas sueltos.

## Decisión

Se construye el frontend comercial alrededor de **un solo producto: la
herramienta creativa web** con el pitch **«del planeta al encuentro»** —
generas un planeta con geología real, lo ves como mapa de fantasía, haces clic
en cualquier punto y obtienes el battlemap coherente con ese lugar.

Prioridad en el front (refleja NEGOCIO §10.2):

| Pieza | Papel en el front nuevo |
|---|---|
| Battlemaps (`/api/batalla/*`) | **Protagonista.** Es lo que paga el nicho; centro del workspace y del pricing. |
| Mapa de fantasía (`/api/fantasia/*`) | **El gancho.** Primera pantalla del workspace, lo que se comparte y enamora. |
| Juego de conquista | **Feature gratis de retención.** Se enlaza desde el mundo («Conquista este mundo»), no se rediseña ni se vende. |
| Generador científico (tectónica, reproductor, extrapolar) | **Oculto.** Es el motor. El panel actual queda accesible en `/lab` para el dueño; el usuario final ve un asistente simplificado (ADR-005). |

## Consecuencias

- La landing vende la herramienta y sus planes; no menciona tectónica de placas
  como producto sino como diferenciador («ríos que corren cuesta abajo de
  verdad»).
- El esfuerzo de UI se reparte ≈ 50% workspace battlemap/fantasía, 30% flujo de
  creación de mundos, 20% landing/pricing — espejo del reparto de NEGOCIO §10.2.
- Nada del back cambia: los tres módulos `_srv` ya son la API del producto.
