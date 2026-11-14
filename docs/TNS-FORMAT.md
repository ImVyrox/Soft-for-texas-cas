# Formato `.tns`

Fuentes: código de [Luna 2.1](https://github.com/ndless-nspire/Luna) (`luna.c` y su minizip
modificado) y análisis de documentos reales descargados de una CX CAS con OS 4.5.5
(`potenciales.tns`, `stopwatch.tns`).

## Contenedor: un ZIP con tres cambios

Un `.tns` **no es un ZIP estándar**, aunque casi:

| Parte | ZIP estándar | `.tns` |
|---|---|---|
| Primera cabecera local | `PK\x03\x04` (4 bytes) | `*TIMLP` + 4 dígitos hex de versión (10 bytes), p. ej. `*TIMLP0601` |
| Resto de cabeceras locales | `PK\x03\x04` | igual |
| Directorio central | `PK\x01\x02` | igual (desplazamientos absolutos) |
| Fin de directorio central | `PK\x05\x06` | `TIPD` |

Versiones vistas: `0500` (Luna por defecto), `0600` (`stopwatch.tns`), `0601` (`potenciales.tns`),
`0700` (Luna cuando añade imágenes BMP).

Componentes vistos:

| Componente | Método ZIP | Contenido |
|---|---|---|
| `Document.xml` | `0x0D` (TI cifrado) | ajustes del documento |
| `Problem1.xml`, `Problem2.xml`… | `0x0D` | contenido de cada problema (páginas, widgets, scripts) |
| `<hash>.BMP` | `8` (deflate normal) | imágenes; se extraen y validan con CRC |

## Entradas cifradas (método `0x0D`)

```
40 bytes de cabecera | cifrado( deflate_crudo( datos XML comprimidos «TIXC» ) )
```

- Cifrado: modo contador con 3DES-ECB. El bloque *i* del flujo es
  `3DES(00 00 00 00 ‖ LE32(base + (i mod 1024)))` y se combina con XOR. Cifrar y descifrar son la
  misma operación. El flujo se repite cada 8 KiB.
- **Cabecera de 40 bytes (TIEN0100), actualizado en la Fase 3:** 3DES-ECB con una clave fija.
  Descifrada contiene `TIEN0100`, el tamaño de bloque (`0x400`), la semilla del contador y las tres
  claves del cuerpo (21 bytes, sin bits de paridad). Los 8 primeros bytes cifrados son siempre
  `0F CE D8 D2 81 06 86 5B` porque cifran `TIEN0100`. Detalle y experimentos en
  [TNS-REVERSE-ENGINEERING.md](TNS-REVERSE-ENGINEERING.md).
- Luna usa siempre la misma cabecera (claves y semilla fijas). Los documentos guardados por TI llevan
  una cabecera propia en **cada entrada**, que ya se puede leer: su XML se descifra y se valida con
  el CRC de TI.
- Metadatos del directorio de una entrada `0x0D`: TI guarda el CRC-32 y el tamaño del **XML
  decodificado**; Luna, los de los **bytes almacenados**.

### Compresión XML «TIXC0100»

`TIXC0100-1.0?>` seguido de un flujo de tokens: diccionarios de nombres de etiqueta y atributo
(`0x0C` inicio por referencia, `0x0E` cierre, `0x0F` atributo por referencia), tablas empaquetadas
para letras y dígitos frecuentes, y una forma compacta para UTF-8. Implementado en `tns/tixc.py`
(port de Rust TNS). Volver a codificar no reproduce el TIXC de TI byte a byte, pero sí el mismo XML.

## Documentos Lua

`Problem1.xml` contiene un único widget `TI.ScriptApp` y el script va en CDATA dentro de
`<sc:script version="512" id="0">`. Cada `]]>` del script se parte en dos secciones CDATA. Luna
genera el documento con un `Document.xml` fijo y la versión `0500`. Requiere OS 3.0.2 o posterior.

## Qué hace el programa (y qué no)

Ver la tabla completa en [COMPATIBILITY.md](COMPATIBILITY.md). En resumen:

| Capacidad | Estado |
|---|---|
| Leer el contenedor de cualquier `.tns` y reescribirlo idéntico | probado con documentos reales y con Luna |
| Descifrar y decodificar el XML de documentos Luna **y nativos** | probado (CRC de TI verificado) |
| Leer propiedades, páginas, widgets, variables y scripts | probado |
| Extraer XML, scripts, imágenes y recursos | probado |
| Crear documentos Lua | idéntico byte a byte a Luna 2.1 |
| Editar el script Lua de documentos Luna | probado, byte a byte |
| Editar el script Lua de documentos nativos | validado aquí; **sin probar en la calculadora** |
| Editar notas, páginas matemáticas, imágenes o Python | no implementado |

## Seguridad de los datos

- El original nunca se modifica. Se guarda siempre como versión nueva, con escritura atómica
  (archivo temporal + `link`/`rename`) y sin sobrescribir salvo confirmación.
- Antes de escribir, el documento reconstruido se vuelve a analizar, se valida su estructura, se
  relee el script y se comprueba que solo cambió el `ProblemN.xml` del script editado.
- Los componentes desconocidos o ilegibles se copian sin tocar.
