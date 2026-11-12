# T07 — nav.js con migas de pan; api.js y ui.js con piezas nuevas

Depende de T06. Spec: «Páginas y navegación».

## Alcance (`frontend/assets/js/`)
- `nav.js`: `montarNav({activa, migas})` (mantener compat con el string
  actual). Sin `migas`: barra de cinco (Pangeira→`/`, Explorar→`/`,
  ＋ Nuevo mundo→`/nuevo`, Pro · $29/año→`/yo#pro`, Entrar→`/yo` o
  email+insignia→`/yo`). Con `migas:[{texto, href}]`: marca › migas (último
  sin enlace) y a la derecha solo Entrar/Yo. «Pro» oculto si `GET /api/cuenta`
  devuelve plan pro/comercial. Reutilizar `.nav`; añadir solo las clases
  imprescindibles para migas en `base.css` (sin cambiar colores ni tipografía).
- `api.js`: `mundo(sello, d?)`, `mundos({orden,q,n})`, `mundoDia(desde?)`,
  `visibilidad(sello, publico)`, `pedirEnlace(email, volver)`, `guardados()`,
  `guardar(item)`, `quitarGuardado(item)`, `cuenta()`. Helpers de URL:
  `urlMundo(sello)`, `urlMapa(sello)`, `urlBattlemap(sello,x,y,q)`,
  `urlJugar(sello)`. Quitar funciones de registro/login con clave si existen.
- `ui.js`: `cuadroCorreo({volver})` reutilizable (campo + «Enviarme el enlace»
  + estado enviado + modo dev muestra aviso) para ★ Guardar sin sesión; y
  `muroPro(texto)` que devuelve el bloque con botón a `/yo#pro`.

## Aceptación
- Montar ambos modos de nav en una página temporal sin errores de consola
  (skill `run` con `python web.py`), o crawl: URLs de la barra → 200/302.
