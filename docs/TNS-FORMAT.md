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
- Las claves y la base del contador se codifican en la cabecera de 40 bytes. Los 8 primeros bytes
  son siempre `0F CE D8 D2 81 06 86 5B`.
- **Solo se conocen las claves de la cabecera fija de Luna** (`TIEN_CRYPTED_HEADER`). Los documentos
  guardados por la calculadora o por el software de TI llevan otra cabecera en cada archivo. Las
  fuentes revisadas no documentan cómo derivar sus claves, así que el programa **no puede leer** el
  XML de esos documentos. Se marca como «clave desconocida» y se conserva intacto.
- En Luna, el CRC y los dos tamaños de una entrada `0x0D` se calculan sobre los bytes almacenados.
  En los documentos de TI, el «tamaño sin comprimir» es el de los datos TIXC.

### Compresión XML «TIXC»

Los datos empiezan por `TIXC0100-1.0?>`. Cada etiqueta de cierre se sustituye por `0x0E` + índice
de la etiqueta abierta. Los caracteres no ASCII de los XML se escapan (ver `escape_unicode` en Luna).
Dentro de una sección CDATA, el texto va tal cual en UTF-8.

## Documentos Lua

`Problem1.xml` contiene un único widget `TI.ScriptApp` y el script va en CDATA dentro de
`<sc:script version="512" id="0">`. Cada `]]>` del script se parte en dos secciones CDATA. Luna
genera el documento con un `Document.xml` fijo y la versión `0500`. Requiere OS 3.0.2 o posterior.

## Qué hace el programa (y qué no)

| Capacidad | Estado |
|---|---|
| Leer el contenedor de cualquier `.tns` y listar sus componentes | implementado y probado con documentos reales |
| Reescribir el contenedor byte a byte idéntico | probado con 2 documentos reales y con la salida de Luna |
| Extraer componentes deflate (imágenes) con verificación CRC | implementado y probado |
| Crear documentos Lua | idéntico byte a byte a Luna 2.1 (probado) |
| Leer y editar el script Lua de documentos creados por Luna o por este programa | implementado y probado |
| Reconstruir conservando byte a byte el resto de componentes | implementado; el validador lo comprueba |
| Abrir en la calculadora un documento generado | **sin probar en hardware** (Luna lleva años usando este formato) |
| Leer o editar el XML de documentos guardados por la calculadora | **no posible**: clave desconocida (pendiente de investigación) |
| Editar un documento Lua después de abrirlo y guardarlo en la calculadora | **no posible**: la calculadora lo guarda con su propia clave |

## Seguridad de los datos

- El original nunca se modifica. Se guarda siempre como versión nueva, con escritura atómica
  (archivo temporal + `link`/`rename`) y sin sobrescribir salvo confirmación.
- Antes de escribir, el documento reconstruido se vuelve a analizar, se valida su estructura, se
  relee el script y se comprueba que solo cambió `Problem1.xml`.
- Los componentes desconocidos o ilegibles se copian sin tocar.
