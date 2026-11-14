# Compatibilidad de documentos

Estado del 2026-11-14 (rama `feature/fase-4-native-editor`).

Columnas:
- **Local:** prueba automática o análisis real en el ordenador. Un documento sintético se indica
  como tal.
- **Hardware:** se abrió el resultado en la TI-Nspire CX CAS (OS 4.5.5) y se comprobó a la vista
  ([HARDWARE-NATIVE-TESTS.md](HARDWARE-NATIVE-TESTS.md)).

## Categorías

| Categoría | Leer | Modificar | Reconstruir | Local | Hardware |
|---|---|---|---|---|---|
| **Completamente inspeccionable**: todas las secciones descifradas y validadas | XML, propiedades, páginas, scripts, recursos | según el tipo (ver abajo) | sí | `potenciales`, `stopwatch`, `Documento1`, Luna | — |
| **Parcialmente inspeccionable**: alguna sección no se puede leer | lo legible; el resto se marca «desconocido» o «protegido» | lo legible | se conserva intacto lo ilegible | sintético | — |
| **Scripts editables**: `TI.ScriptApp` | script Lua, título, versión | el script | sí | `stopwatch` real y sintéticos | 🔩 `stopwatch` editado se abre y funciona |
| **Notas editables**: `TI.Notepad` | texto, cuadros matemáticos, imágenes | texto de fragmentos existentes | sí | `Documento1` real y sintéticos | 🔩 texto con ñ y tildes correcto |
| **Matemáticas editables** | entrada y resultado en caché de los cuadros | **no** | — | `Documento1` | — |
| **Solo extracción**: imágenes, recursos, Python | contenido / BMP visible | no | se conservan byte a byte | `potenciales` (BMP) | — |
| **Protegidos**: script con `sc:cry≠0` o cabecera que no es TIEN0100 | se marcan «protegido» | no | se conservan | sintético | — |

## Documentos concretos

| | `potenciales.tns` | `stopwatch.tns` | `Documento1.tns` | `P2.tns` | `hello_luna.tns` |
|---|---|---|---|---|---|
| Origen | TI software 6.3 | TI software 5.0 | calculadora OS 4.5.5 (muestra del usuario) | — | Luna 2.1 |
| Estructura | 3 secciones | 2 secciones | 2 secciones | **sin copia** (documento abierto en la calculadora) | 2 secciones |
| Páginas | 4 notas (1 imagen, 3 vacías) | 1 Script Lua | 2 notas | — | 1 Script Lua |
| Estado | completamente inspeccionable | completamente inspeccionable | completamente inspeccionable | — | completamente inspeccionable |
| Editable | no hay texto | script 🔩 | texto de notas 🔩; matemáticas no | — | script |
| Reconstrucción sin cambios | contenedor idéntico byte a byte | igualdad estructural | — | — | byte a byte |

## Qué se puede editar realmente

- **Editable y verificado en hardware:**
  - el script Lua de documentos nativos `TI.ScriptApp`;
  - el texto de fragmentos de notas existentes (letras, incluidas `ñ` y vocales con tilde, números,
    espacios, `π` y puntuación básica).
- **Editable, verificado en local:** el script de documentos Luna o creados por la aplicación (con
  reconstrucción idéntica a Luna).
- **Solo inspección y extracción:**
  - cuadros matemáticos;
  - imágenes y recursos;
  - páginas que no son ni notas ni Lua (no hay muestras de calculadora, gráficos, geometría ni
    listas);
  - Python;
  - contenido protegido.
