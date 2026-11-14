# Editor `.tns`

## Flujo seguro

1. **Abrir.** Se lee el archivo una vez y se analiza en un hilo de trabajo.
2. **Analizar.** Se identifican secciones, cabeceras, XML, scripts y recursos (`tns/inspect.py`).
3. **Editar.** Solo los scripts Lua no protegidos son editables; el resto es de solo lectura.
4. **Reconstruir.** El documento se rehace en memoria (`tns/edit.py`):
   - Solo cambia el `ProblemN.xml` del script editado. Las demás entradas se copian byte a byte
     (comprobado: si cambia otra, la reconstrucción se rechaza).
   - Documentos Luna: misma salida que Luna 2.1.
   - Documentos nativos: se sustituyen solo los bytes del script dentro del XML, se recodifica a
     TIXC y se cifra con la **cabecera original** de esa entrada (mismas claves y semilla). El
     CRC y el tamaño siguen la convención original de la entrada.
5. **Validar.** Se vuelve a analizar el resultado: estructura, CRC, descifrado de todo el XML,
   script releído idéntico y reescritura del contenedor idéntica. Si está instalado `luac5.1`, se
   comprueba también la sintaxis Lua 5.1 y se marca la línea con error.
6. **Guardar como.** El resultado se escribe en un archivo nuevo, de forma atómica. Guardar sobre
   el original está prohibido.

## Páginas y párrafos (Fase 5)

- En «Páginas» aparecen todas las páginas, de cualquier aplicación (Notas, Lua, Calculadora,
  Gráficos y geometría, Listas, Datos).
- Las páginas que no son de notas se muestran como resumen de solo lectura: entradas y resultados de
  Calculadora, objetos, columnas y fórmulas, tipo de gráfico.
- En las páginas de notas, la tabla tiene una fila por párrafo. Los párrafos de texto se editan con
  doble clic y se pueden insertar (＋), eliminar (－) y mover (▲▼). Los párrafos con objetos muestran
  como filas hijas su texto (editable) y sus cuadros matemáticos (forma lineal y resultado, solo
  lectura).
- «◀ Página / Página ▶» cambia el orden de las páginas.
- **Deshacer / Rehacer** de la barra actúa sobre el script si está a la vista y, si no, sobre las
  ediciones de páginas.
- La vista previa de cambios muestra los párrafos antes y después, y el nuevo orden de páginas.

## Notas (Fase 4)

En el explorador aparece la sección «Páginas». Cada página se marca como **editable**, **solo
lectura**, **desconocido** o **protegido**. Al elegir una página de notas se muestra una tabla con
sus elementos (texto, cuadros matemáticos e imágenes).

Con doble clic se edita el texto de los fragmentos marcados como editables. Solo se aceptan letras
(incluidas á é í ó ú ü ñ), números, espacios, `π` y puntuación básica. Los cuadros matemáticos son de
solo lectura. Detalles en [NOTES-FORMAT.md](NOTES-FORMAT.md). Verificado en hardware
([HARDWARE-NATIVE-TESTS.md](HARDWARE-NATIVE-TESTS.md)).

## Interfaz

- **Pestañas:** un documento por pestaña; `*` en el título indica cambios sin guardar. Al cerrar
  una pestaña o la aplicación con cambios, se pide confirmación.
- **Panel izquierdo (Explorador):** Scripts, XML, Recursos y Secciones binarias.
- **Panel central:** editor Lua, visor XML (un elemento por línea, solo lectura), visor de
  imágenes, información y primeros bytes de cada sección.
- **Panel derecho:**
  - **Propiedades:** informe del documento o de la sección elegida (codificación, tamaños, cabecera
    TIEN, semilla, convención de metadatos y SHA-256).
  - **Historial:** registro de lo hecho en el documento (abrir, editar, formatear, validar,
    reconstruir, guardar, extraer).
- **Barra de acciones:** Nuevo (documento Lua vacío o desde un `.lua`), Abrir, Guardar como,
  Extraer, Reconstruir, Validar, Formatear, Comparar (vista previa de cambios o con otro `.tns`) y
  Enviar. Las acciones no disponibles quedan deshabilitadas y su descripción explica por qué.

## Editor Lua

| Función | Cómo |
|---|---|
| Resaltado y números de línea | `LuaHighlighter`, margen propio |
| Autocompletado | Ctrl+Espacio: palabras clave, biblioteca estándar, API habitual de TI-Nspire y los identificadores del documento |
| Indentación automática | Intro mantiene la sangría y añade un nivel tras `then`, `do`, `else`, `repeat`, `function(...)`, `{` y `(` |
| Buscar / reemplazar | Ctrl+F / Ctrl+H; «Todo» se deshace en un solo paso |
| Deshacer / rehacer | Ctrl+Z / Ctrl+Shift+Z |
| Errores de sintaxis | `luac5.1 -p` al validar y también mientras se escribe (tras una pausa de 1,2 s); marca la línea con error. Si `luac5.1` no está instalado se avisa, en vez de fingir la comprobación |
| APIs no disponibles | Aviso con marca en el margen para `io`, `os`, `debug`, `file`, `dofile`, `loadfile` y `module` (no existen en TI-Nspire) |
| Navegación | Lista de funciones del script; al elegir una se salta a su línea |
| Plegado | Clic en ▾/▸ del margen para plegar o desplegar `function`/`do`/`then`/`repeat` … `end`/`until` |
| Formatear | Reindenta con la sangría del propio script; solo se aplica si `luac5.1 -s` da el mismo bytecode antes y después |
| Búsqueda avanzada | Opciones de regex (con grupos `\1` en el reemplazo) y palabra completa |

## Comparación

Para el documento entero se informa del nivel de igualdad más fuerte que se cumple:

| Nivel | Significado |
|---|---|
| igualdad byte a byte | los dos archivos son idénticos |
| igualdad estructural | mismas secciones, orden, métodos y versión; cada sección decodifica al mismo contenido |
| igualdad de contenido | mismo contenido, distinta estructura (p. ej. versión del contenedor) |
| reconstrucción no verificable | alguna sección no se puede decodificar en uno de los dos |
| documentos distintos | hay contenido diferente (p. ej. el script editado) |

Además se lista cada sección (igual / contenido igual / modificado / añadido / eliminado / no
verificable) y se muestran las diferencias de texto de scripts y XML.

## Extracción

*Extraer…* crea una carpeta nueva «`<nombre> (extraído)`» y nunca escribe en una existente. Contiene:
- el XML decodificado de cada entrada cifrada;
- los recursos sin cifrar;
- un `.lua` por script;
- `informe.txt` con el análisis.

Ejemplo de informe (real, `stopwatch.tns`):

```
Documento: stopwatch.tns
Formato: TI-Nspire (.tns)
Firma: válida (*TIMLP / TIPD)
Versión: 0600 (cabecera *TIMLP0600)
Origen: nativo (calculadora o software TI)
Contenido: TI.ScriptApp
Secciones: 2
Bloques XML: 2
Bloques comprimidos: 2
Bloques cifrados: 2 (descifrables: 2)
Scripts Lua: 1 (1 script(s) Lua, editables)
Recursos: 0
Reescritura del contenedor idéntica: sí
Estado: completamente interpretable
Creado con: 5.0.0.752 CE CAS Win
```
