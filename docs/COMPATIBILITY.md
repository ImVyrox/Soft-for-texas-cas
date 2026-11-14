# Compatibilidad de documentos

Estado del 2026-11-14 (rama `feature/fase-3-editor-tns`). «Probado» significa que hay una prueba
automática o un análisis real que lo comprueba, no solo que el documento se abre sin errores.

## Documentos concretos (copias locales)

| | `potenciales.tns` | `stopwatch.tns` | `P2.tns` | `hello_luna.tns` (Luna) |
|---|---|---|---|---|
| Estructura reconocida | sí (`*TIMLP0601`, 3 secciones) | sí (`*TIMLP0600`, 2 secciones) | **sin copia local** | sí (`*TIMLP0500`, 2) |
| Metadatos legibles | sí: software 6.3.0.119 SE CAS, idioma `es`, ajustes | sí: software 5.0.0.752 CE CAS, idioma `en` | — | ajustes del `Document.xml` de Luna |
| XML | 2 bloques, descifrados; CRC de TI verificado | 2 bloques, descifrados; CRC de TI verificado | — | 2 bloques (CRC legacy verificado) |
| Bloques cifrados | 2 (cabecera propia), descifrables | 2 (cabecera propia), descifrables | — | 2, descifrables |
| Recursos | 1 BMP 182×187, extraíble y visible | 0 | — | 0 |
| Scripts | 0 (4 páginas `TI.Notepad`) | 1 Lua (`Stopwatch`, 83 333 caracteres, no protegido) | — | 1 Lua |
| Reconstrucción sin pérdida | contenedor idéntico byte a byte; sin script que editar | mismo script → **igualdad estructural** (`Document.xml` idéntico byte a byte, `Problem1.xml` mismo XML) | — | mismo script → **byte a byte** |
| Edición posible | inspeccionar, extraer XML e imagen | **editar el script Lua** (*) | — | editar el script Lua |
| Estado | completamente interpretable | completamente interpretable | — | completamente interpretable |

(*) La reconstrucción del documento nativo se valida en el programa (estructura, CRC con la
convención de TI, script releído, resto de componentes intactos), pero **no se ha probado
abriéndolo en la calculadora**: en esta fase no se permitían escrituras.

Para analizar `P2.tns`: ciérralo en la calculadora, descárgalo con la aplicación y ábrelo en el
editor.

## Por tipo de documento

| Tipo | Inspeccionar | Extraer | Editar | Base |
|---|---|---|---|---|
| Lua generado con Luna / este programa | ✅ | ✅ | ✅ byte a byte | probado (Luna de referencia) |
| Lua nativo (`TI.ScriptApp` guardado por TI) | ✅ | ✅ | 🧪 script; validado aquí, sin probar en la calculadora | `stopwatch.tns` + sintéticos |
| Script marcado `sc:cry≠0` | ✅ (como «protegido») | ✅ XML | ❌ no se modifica | solo sintético |
| Páginas matemáticas / notas (`TI.Notepad`) | ✅ XML en bruto | ✅ | ❌ (no hay editor de notas) | `potenciales.tns` |
| Varias páginas (`<card>`) | ✅ | ✅ | scripts de cada problema | `potenciales.tns` (4 páginas) |
| Varios problemas (`Problem2.xml`…) | ✅ | ✅ | ✅ por problema | sintético (código general, sin muestra real) |
| Imágenes BMP | ✅ visor (Qt o RGB565 de TI) | ✅ | ❌ | `potenciales.tns` |
| Otros recursos | ✅ como «Recurso» | ✅ | ❌ | sintético |
| Python (`TI.PythonEditor`, CX II) | detecta el widget y los archivos referenciados | ✅ | ❌ | **sin muestras** |
| Entrada con cabecera que no es TIEN0100 | ✅ marcada «protegida» | ❌ su contenido | ❌ | sintético |
| Método de compresión desconocido | ✅ marcado como error | ❌ | ❌ | sintético |

## Qué se puede editar realmente

- **Editable y verificado:** el script Lua de documentos Luna o creados por esta aplicación.
- **Editable, sin verificar en la calculadora:** el script Lua de documentos `TI.ScriptApp` nativos
  (p. ej. `stopwatch.tns`).
- **Solo inspección y extracción:** notas y páginas matemáticas, imágenes, documentos Python, scripts
  protegidos y cualquier componente que no sea un script Lua.
