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

## Interfaz

- **Pestañas:** un documento por pestaña; `*` en el título indica cambios sin guardar. Al cerrar
  una pestaña o la aplicación con cambios, se pide confirmación.
- **Panel izquierdo (Explorador):** Scripts, XML, Recursos y Secciones binarias.
- **Panel central:** editor Lua, visor XML (un elemento por línea, solo lectura), visor de
  imágenes, información y primeros bytes de cada sección.
- **Panel derecho (Propiedades):** informe del documento o de la sección elegida: codificación,
  tamaños, cabecera TIEN, semilla, convención de metadatos y SHA-256.
- **Barra de acciones:** Nuevo Lua, Abrir, Importar .lua, Guardar como, Extraer, Reconstruir,
  Validar, Comparar (con el original o con otro `.tns`) y Enviar a la calculadora. Las acciones no
  disponibles quedan deshabilitadas y su descripción explica por qué.

## Editor Lua

| Función | Cómo |
|---|---|
| Resaltado y números de línea | `LuaHighlighter`, margen propio |
| Autocompletado | Ctrl+Espacio: palabras clave, biblioteca estándar, API habitual de TI-Nspire y los identificadores del documento |
| Indentación automática | Intro mantiene la sangría y añade un nivel tras `then`, `do`, `else`, `repeat`, `function(...)`, `{` y `(` |
| Buscar / reemplazar | Ctrl+F / Ctrl+H; «Todo» se deshace en un solo paso |
| Deshacer / rehacer | Ctrl+Z / Ctrl+Shift+Z |
| Errores de sintaxis | `luac5.1 -p` al validar (Lua 5.1, como TI-Nspire); si no está instalado se avisa y no se finge la comprobación |

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
