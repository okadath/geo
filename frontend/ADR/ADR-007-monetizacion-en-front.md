# ADR-007 — Monetización en el front: planes visibles, pasarela diferida

**Estado:** aceptada · 2026-07-17

## Contexto

El plan de negocio es freemium por suscripción vía Paddle (NEGOCIO §9.4/§10.1:
Free / Pro $4.99mes·$29año / Comercial $9.99mes·$59año, anual por defecto).
Pero cuentas, sesiones y pasarela son trabajo de back (PLATAFORMA §2, semanas
1–4) que este proyecto de front **no** incluye.

## Decisión

El front se construye **listo para la pasarela pero honesto sin ella**:

- La landing muestra la tabla de planes completa con el **anual como botón
  destacado** (regla de NEGOCIO §9.2: la comisión fija se diluye 12×).
- Los botones de pago llevan, mientras no exista Paddle, a un formulario de
  **lista de espera** (mailto prellenado) etiquetado «beta — acceso anticipado».
  Nunca un checkout falso.
- Las capacidades de pago aparecen en la UI como insignias «Pro» informativas
  (p. ej. calidad 4×, export 8K, battlemap 140 px), pero **no se bloquea nada
  en JS**: el gating real debe aplicarse en el servidor cuando existan cuentas
  (PLATAFORMA §1.2 — «nunca en JS»). Hoy todo funciona, mañana el servidor
  limita y la UI ya sabe mostrarlo.

## Consecuencias

- Cero deuda: cuando llegue Paddle solo se cambia el destino de dos botones y
  el servidor empieza a responder los límites que la UI ya sabe señalar.
- Durante la beta los usuarios tienen acceso Pro de facto; es la estrategia
  correcta de soft-launch (PLATAFORMA §3.2) y se comunica como tal.
