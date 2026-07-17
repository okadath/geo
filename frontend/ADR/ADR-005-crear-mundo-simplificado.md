# ADR-005 — Crear mundo: presets + «preparar mundo» encadenado, diales ocultos

**Estado:** aceptada · 2026-07-17

## Contexto

Hoy crear un mundo usable exige entender ~16 diales de tectónica
(`POST /api/generar`), esperar, elegir un checkpoint del reproductor, y luego
otros ~11 diales de detallado (`POST /api/detallar`) para obtener el detalle
con civilización que las herramientas necesitan. Dos pasos manuales expertos
— inutilizable para un DM.

## Decisión

El asistente de `/estudio` reduce todo a **una decisión + un botón**:

1. **Preset de mundo** (4 tarjetas): *Continentes* (equilibrado, default),
   *Pangea*, *Archipiélago*, *Sorpréndeme* (semilla aleatoria). Cada preset es
   un mapeo fijo a los parámetros de `PARAMS`; el usuario solo puede tocar la
   semilla si quiere.
2. Botón **«Forjar mundo»** que encadena automáticamente:
   `POST /api/generar` → polling `/api/estado` → al terminar, elegir el
   **último checkpoint** de `mapa_repro.json` → `POST /api/detallar` con
   valores por defecto (civilización incluida) → polling → abrir
   `/estudio/mundo`. Una sola barra de progreso con dos fases y textos vivos
   («enfriando la corteza…», «trazando ríos…», «fundando reinos…»).
3. Un acordeón **«Ajustes avanzados»** plegado expone los diales completos
   para usuarios expertos, sin estorbar al resto.

## Consecuencias

- El tiempo de espera (minutos de CPU) no se puede ocultar, pero sí narrar:
  la barra con textos de fase convierte el costo en espectáculo — coherente
  con que los GIFs de tectónica son el marketing (NEGOCIO §10.3).
- El detallado usa defaults fijos; si un preset produce mundos malos se ajusta
  el preset (config), no la UI.
- Los mundos ya existentes en `salidas/` con detalle+civilización aparecen en
  la galería y funcionan igual: el asistente es azúcar, no un formato nuevo.
