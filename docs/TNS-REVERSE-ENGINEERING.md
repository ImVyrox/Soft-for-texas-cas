# Ingeniería inversa del formato `.tns` (Fase 3)

Fecha: 2026-11-13/14. Solo se trabajó sobre copias locales; no se hicieron escrituras en la
calculadora.

Marcas: **[H]** hecho comprobado (con el experimento que lo demuestra) · **[P]** hipótesis o dato
de una fuente no verificado aquí.

## Muestras

| Archivo | Origen | Uso |
|---|---|---|
| `potenciales.tns` | descargado de la CX CAS del usuario (solo lectura) | copia local, **no está en Git** |
| `stopwatch.tns` | widget preinstalado de TI, descargado igual | copia local, **no está en Git** |
| `P2.tns` | documento abierto en la calculadora | **no disponible**: la calculadora no lo entrega mientras está abierto (ver USB-PROTOCOL.md). Hace falta una copia (cerrándolo antes) para analizarlo |
| `tests/fixtures/hello_luna.tns` | generado con Luna 2.1 | en Git |
| documentos sintéticos de tipo nativo | `tests/native_fixture.py` | en Git, generados en las pruebas |

## Referencias consultadas

| Fuente | Qué aporta |
|---|---|
| [Luna](https://github.com/ndless-nspire/Luna) (`luna.c`, minizip modificado; MPL 1.1) | Contenedor `*TIMLP`/`TIPD`, método `0x0D`, cifrado del cuerpo con claves fijas y cabecera fija, plantilla Lua |
| [nsptools-history](https://github.com/ndless-nspire/nsptools-history) | Luna v0.1a (mismo esquema) y símbolos del OS 3.x de Ndless: `compress_encrypt_tns`, `crypt_decrypt_tns_D_block`, `DES_decrypt3`. **[H]** el descifrado lo hace el propio OS |
| [Rust TNS](https://github.com/dev1837457/rust-tns) (commit `48a6f5e`, MPL 1.1, proyecto de interoperabilidad) | Estructura de la cabecera `TIEN0100`, su clave fija, el formato TIXC0100 completo y las dos convenciones de CRC |
| [Hackspire](https://hackspire.org) | El proxy de descarga lo bloquea; no se pudo consultar en esta fase |
| Búsquedas web | TnsTools y «TNS Tool WASM» citados como herramientas que también leen el formato **[P]** (no revisadas) |

No se usó ingeniería inversa del sistema operativo de TI, ni fuerza bruta, ni código de TI.

## Experimentos y resultados

### E1. Cabecera de 40 bytes de las entradas `0x0D` **[H]**

Rust TNS describe la cabecera como `TIEN0100` cifrado con 3DES-ECB bajo una clave fija de 24
bytes. Comprobación independiente de esa clave con los datos de Luna, que no dependen de Rust TNS:
- La cabecera fija de Luna se descifra a `TIEN0100`, tamaño de bloque `0x400` y semilla
  `0x6FE21307`, que es el `IVEC_BASE` de `luna.c`.
- Sus 21 bytes de clave, expandidos con paridad, dan **exactamente** las tres claves 3DES que
  `luna.c` tiene escritas (`16A7A732…`, `D9A886A4…`, `3D808CB5…`).
- Con eso se explican los «8 bytes comunes» (`0F CE D8 D2 81 06 86 5B`) que ya se habían visto en
  la Fase 1: son el cifrado de `TIEN0100`.

Prueba automática: `test_luna_header_decrypts_to_lunas_keys_and_seed`.

### E2. Documentos nativos **[H]**

En `potenciales.tns` y `stopwatch.tns`, cada entrada `0x0D` lleva **su propia** semilla y sus
propias claves (p. ej. `0xEE6DF4B6` y `0xF5EC56EB` en las dos entradas de `potenciales.tns`), y
todas se descifran e inflan a un flujo `TIXC0100-1.0?>`. Prueba decisiva: el XML decodificado
coincide con el **CRC-32 y el tamaño guardados por TI** en el directorio, en las 4 entradas
(1180, 8992, 1096 y 84 064 bytes). Una decodificación errónea no daría el mismo CRC.

### E3. Dos convenciones de metadatos **[H]**

| Generador | CRC-32 / tamaño sin comprimir del directorio |
|---|---|
| Calculadora y software de TI (5.0, 6.3) | del **XML decodificado** (`final`) |
| Luna / Texas CAS Manager | de los **bytes almacenados** (`legacy`) |

La reconstrucción respeta la convención que tenía cada entrada.

### E4. TIXC no es único **[H]**

Volver a codificar el XML de TI produce un TIXC distinto del original. El codificador de Rust TNS
(y el de este proyecto) evita las referencias de atributo `0x0F`, que TI sí usa. Sin embargo,
`decode(encode(xml)) == xml` siempre. Consecuencia: un documento nativo reconstruido tiene
**igualdad estructural**, no byte a byte (`stopwatch.tns` con el mismo script → igualdad
estructural; `Document.xml` sigue idéntico byte a byte).

### E5. Imagen BMP de TI **[H]**

`BB2BF559….BMP` (deflate) es un BMP de 182×187, 16 bits, `BI_BITFIELDS`, con las máscaras
desplazadas 16 bits (`0xF8000000`, `0x07E00000`, `0x001F0000`). Qt no lo abre. Decodificado como
RGB565 de abajo arriba se ve un dibujo coherente (comprobado visualmente). Sigue siendo **[P]** que
TI use siempre esta variante.

### E6. Contenido XML **[H]**

- `Document.xml`: `<properties>` (`product`, `platform`, `swver` = versión del software que lo
  guardó, `date`) y `<settings>` (idioma, formatos, ángulos, modo CAS…).
- `ProblemN.xml`: `<prob xmlns="urn:TI.Problem">`, que **declara un espacio de nombres por defecto**;
  `<sym>` lleva las variables y cada `<card>` es una página con un `<wdgt type=…>`.
- `potenciales.tns`: 1 problema con 4 páginas `TI.Notepad`. El texto va en `np:fmtxt` como marcado
  enriquecido escapado (`<r2dtotree>…`).
- `stopwatch.tns`: 1 página `TI.ScriptApp`; el script Lua va en claro en CDATA (`sc:cry=0`) junto
  con `sc:guid`, `sc:md` (título, versión) y `sc:script version="34013703"`.

### Hipótesis abiertas **[P]**

- `sc:cry` distinto de 0 indicaría un script protegido o cifrado por TI. No hay muestra real: el
  programa los marca como protegidos y no los modifica.
- Formato interno de `np:fmtxt` (texto de las notas): sin estudiar; se muestra en bruto.
- Documentos Python (`TI.PythonEditor`, archivos `.py` en el contenedor, CX II): sin muestras.
- Si la calculadora acepta un documento nativo reconstruido (TIXC distinto, misma cabecera): **no
  probado en hardware**. Rust TNS dice que sus documentos son interoperables, pero no se ha
  verificado aquí.
