# T08 — Portada `/` y ficha `/w/<sello>`

Depende de T07. Spec: tabla de rutas; ficha = grilling ronda 3 variante 1; portada = ronda 6 variante 3.

## Alcance
`frontend/explorar.html` + `assets/js/explorar.js`:
- Cabecera «Mundo del día · «Nombre» #sello» con enlaces «ficha» y
  «siguiente ▸» (`mundoDia(desde)`); el visor existente (`visor.js`) embebido
  con el mundo del día; clic en el mapa → `urlBattlemap`.
- Tira horizontal «Más mundos» (`mundos({orden:"nuevos", n:12})`) con
  miniatura, nombre y #sello → ficha.
- Filtros: nuevos · al azar (`orden=azar`) · buscador de semilla/nombre (`q`).
- Estado vacío sin públicos: texto + enlace a `/nuevo`.
`frontend/ficha.html` + `assets/js/ficha.js`:
- Lee `sello` del path; `mundo(sello, d?)`; error elegante si 404.
- Bloque superior: imagen a la izquierda; a la derecha datos (semilla, placas,
  continentes, clima, países si existen), botones «Abrir mapa» (principal) y
  «Jugar»; fila «⧉ Copiar enlace», «★ Guardar», «Remezclar semilla».
  ★ sin sesión → `cuadroCorreo({volver: location.pathname})`; con sesión →
  `guardar({tipo:"mundo", sello})`. Remezclar → pro: `/nuevo?semilla=…`;
  si no: `muroPro`.
- Conmutador de visibilidad solo si `dueno === email` de la sesión.
- «Battlemaps destacados»: cuadrícula con `lugares` → `urlBattlemap(sello,x,y)`.
- Muro Pro al final si plan no pro.
- Migas: `[{texto: nombre}]`. Marcadores OG en `<head>` como define T06.
- Hojas CSS: reutilizar `estudio.css`/`landing.css` existentes renombradas o
  una `explorar.css`/`ficha.css` mínimas; sin cambios de tokens.

## Aceptación
- Carga sin errores de consola con una corrida pública real de `salidas/`.
- Todos los enlaces responden 200/302 (crawl).
- El HTML de la ficha servido por el servidor contiene las metas OG rellenas.
