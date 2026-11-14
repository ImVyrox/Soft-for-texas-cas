# Arquitectura

```
src/texas_cas_manager/
├── app.py              arranque (QApplication, traducciones, registro)
├── config.py           ajustes JSON, escritura atómica, nombres únicos, logging
├── core/
│   ├── link.py         interfaz Link + HelperLink (USB vía tcm-link) + MockLink (simulada)
│   └── demo.py         contenido de la calculadora simulada
├── tns/                formato .tns (sin Qt: se prueba sin interfaz)
│   ├── container.py    lector/escritor del contenedor *TIMLP/TIPD (analizador binario)
│   ├── tien.py         cabecera TIEN0100 de las entradas cifradas (MPL)
│   ├── doccrypt.py     cifrado del cuerpo (3DES en modo contador) + deflate
│   ├── tixc.py         codificador/decodificador XML TIXC0100 (MPL)
│   ├── xmldoc.py       lectura del XML (propiedades, widgets, scripts) y sustitución de scripts
│   ├── images.py       BMP de 16 bits de TI
│   ├── _luna_data.py   constantes de Luna 2.1 (MPL)
│   ├── lua.py          crear documentos Lua, leer y sustituir scripts (Luna y nativos)
│   ├── notes.py        páginas de notas: lectura y edición acotada de texto
│   ├── xmlentry.py     reescritura de una entrada XML nativa (misma cabecera TIEN)
│   ├── inspect.py      análisis, informes y validación
│   ├── edit.py         reconstrucción verificada y comparación por niveles
│   └── extract.py      exportación de componentes
├── editor/lua_tools.py autocompletado, indentación, sintaxis, plegado, funciones, formato seguro, avisos TI (sin Qt)
└── ui/
    ├── main_window.py  barra superior, navegación lateral, páginas, barra de estado
    ├── theme.py        temas claro/oscuro (tokens → hoja de estilo Qt)
    ├── workers.py      tareas en segundo plano, LinkService (detección y cola USB)
    ├── pages/          inicio, calculadora, archivos locales, editor, herramientas, ajustes
    └── widgets/        editor de código Lua, buscar/reemplazar, tarjetas, notificaciones, iconos
native/tcm-link/        helper USB en C (libticalcs2)
```

## Principios

- **Capas separadas.** `tns/` y `core/` no importan Qt. La GUI solo llama a `Link` y a funciones
  de `tns/`.
- **Nada bloquea la interfaz.** Las operaciones USB pasan por `LinkService`, que tiene un pool de
  un solo hilo porque la calculadora atiende una petición cada vez. El análisis de documentos usa
  el pool global.
- **Aislamiento del USB.** libticalcs corre en un proceso hijo con protocolo JSON por líneas.
- **Datos seguros.** El original nunca se modifica, la escritura es atómica, se valida antes de
  escribir, los componentes desconocidos se conservan y se pide confirmación antes de borrar en la
  calculadora (no se puede deshacer). En local se usa la papelera.
- **Extensible.** Un backend nuevo (libnspire, CX II) implementa `Link`. Un tipo de componente
  nuevo se añade en `tns/inspect.py` y en el editor.

## Flujo de detección

`LinkService` llama a `probe` cada 3 s. Solo enumera USB y no abre enlace. Si aparece una TI y la
conexión automática está activa, ejecuta `open` + `info`. Mientras está conectada, el mismo
`probe` detecta la desconexión.
