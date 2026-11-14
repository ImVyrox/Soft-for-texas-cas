# Pruebas en hardware de documentos nativos editados

Calculadora: TI-Nspire CX CAS, OS 4.55.0079 (según libticalcs). Cada envío lo autorizó el usuario
expresamente, después de ver el archivo, su tamaño, su hash y el destino. Solo se escribió en
`/TCM_TESTS`, no se borró nada y no se tocaron los archivos personales.

Herramienta: `scripts/native_hw_test.py`:
- `prepare` trabaja solo en local: copia, edita, reconstruye, valida, compara y calcula SHA-256.
- `upload` comprueba el estado de la calculadora, envía, lista, vuelve a descargar y compara el
  SHA-256. Se detiene si el destino ya existe o si algo no cuadra.

## Prueba 1 — script Lua de un documento nativo (2026-11-14)

| Paso | Resultado |
|---|---|
| Original | `stopwatch.tns`, 16 772 B, SHA-256 `7c80464e…6f5df7`. El original no se modificó (copia en local) |
| Edición | línea 2848 del script: `setLabel '0:00:00.00'` → `setLabel 'TCM 0:00:00.00'` |
| Reconstrucción | `stopwatch_tcm.tns`, 16 697 B, SHA-256 `03967a53…0e9842` |
| Validación | sin problemas; `Document.xml` idéntico byte a byte; `Problem1.xml` es el único componente modificado; misma cabecera TIEN (mismas claves y semilla); CRC del directorio = CRC del XML nuevo (convención de TI) |
| Diferencia del XML | 4 bytes insertados (`TCM `) en la posición 76 976; el resto es idéntico |
| Envío | `/TCM_TESTS/stopwatch_tcm.tns`: 16 697 B; listado correcto; descargado de nuevo con el **mismo SHA-256** |
| En la calculadora (comprobado por el usuario) | se abre sin errores, muestra **«TCM 0:00:00.00»**, y al iniciar, pausar, contar y reiniciar se comporta como el original |

## Prueba 2 — texto de una página de notas (2026-11-14)

| Paso | Resultado |
|---|---|
| Original | `Documento1.tns`, creado por el usuario en la calculadora para la prueba: 1 591 B, SHA-256 `a1001e7b…0b0d`. Se descargó para la lectura y no se modificó |
| Edición | página 1: `hola` → `Hola TCM ñandú 123`, `abcn` → `Página editada` |
| Reconstrucción | `notas_tcm.tns`, 1 589 B, SHA-256 `e5668fbd…32ce` |
| Validación | sin problemas; los cuadros matemáticos y la página 2 sin cambios; `Document.xml` idéntico byte a byte |
| Envío | `/TCM_TESTS/notas_tcm.tns`: 1 589 B; descargado de nuevo con el **mismo SHA-256** |
| En la calculadora (comprobado por el usuario) | se abre sin errores; el texto se ve correcto, con `ñ` y tildes; el cuadro matemático sigue mostrando 4; la página 2 (`π`, `n`) y la edición normal funcionan |

## Conclusiones

- **Demostrado en hardware:**
  - Editar el script Lua de un documento nativo y reconstruirlo con su propia cabecera TIEN.
  - Editar el texto de fragmentos de notas existentes, incluidos `ñ` y vocales con tilde.
- **No demostrado todavía:** otros tipos de página, añadir o quitar fragmentos, los caracteres
  fuera del conjunto permitido y los documentos con varios problemas.

## Estado de `/TCM_TESTS` tras las pruebas

`stopwatch_tcm.tns`, `notas_tcm.tns` y `Documento1.tns` (este último lo creó el usuario). No se
borró ninguno.
