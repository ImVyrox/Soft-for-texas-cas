# Comunicación USB con la TI-Nspire

Estado: investigado y probado con hardware real el 2026-11-13 (TI-Nspire CX CAS, OS 4.5.5.79,
Boot2 4.5.0.14, USB `0451:e012`, CachyOS, libticalcs2 1.1.9). Todas las pruebas con hardware fueron
de solo lectura: información, listados y descargas.

## Capas

```
GUI (PySide6) ── LinkService (un hilo de trabajo) ── HelperLink ──stdin/stdout JSON──▶ tcm-link (C)
                                                                                        │
                                              libticalcs2 (reset, direcciones, paquetes) ─ libusb
```

`tcm-link` (`native/tcm-link/tcm_link.c`) es un proceso hijo. Si libusb se cuelga o falla, la GUI
sigue viva. De libticalcs se usa la apertura del enlace (`ticalcs_calc_isready`) y el envío y
recepción de paquetes (`nsp_send`/`nsp_recv`, que calculan checksums y números de secuencia). El
diálogo con los servicios de la calculadora lo lleva el helper (ver «Por qué no se usan las
funciones de alto nivel»).

## Protocolo (NavNet)

Fuentes: código de libticalcs (`calc_nsp.cc`, `nsp_cmd.cc`, `nsp_vpkt.cc`, `nsp_rpkt.cc`), de
libnspire (`services/file.c`, `data.c`, `packet.c`) y la página
[USB Protocol de Hackspire](https://hackspire.org/index.php/USB_Protocol).

- Paquetes de hasta 254 bytes de datos. El primer byte es el comando, así que los trozos de
  archivo son de 253 bytes.
- Direcciones: ordenador `0x6400`, calculadora `0x6401`. Tras un reset USB, la calculadora pide
  una dirección (`0x4003`).
- Cada paquete de datos se confirma con un ACK: puerto origen `0x00FF`, `AK=0x0A`, mismo número de
  secuencia, datos = puerto que lo recibió. Un NACK usa el puerto origen `0x00D3`.
- Para desconectarse de un servicio se envía un paquete desde el puerto `0x40DE` con el puerto
  propio como datos.
- Servicios usados: `0x4020` información del dispositivo y `0x4060` gestión de archivos.

### Servicio de archivos `0x4060`

| Operación | Petición | Respuesta |
|---|---|---|
| Listar | `0D ruta` → `0E` repetido → `0F` | `FF 00`; cada `0E` da `10 …` (nombre, tamaño, tipo) o `FF 11` (fin) |
| Descargar | `07 01 ruta` → `04` → `FF 00` final | `03 01 … tamaño`, luego `05 contenido` |
| Enviar | `03 01 ruta tamaño` → `05 contenido` | `04`, luego `FF 00` |
| Borrar archivo | `09 01 ruta` | `FF xx` |
| Crear / borrar carpeta | `0A 03 ruta` / `0B 03 ruta` | `FF xx` |
| Renombrar | `21 01 ruta ruta2` | `FF xx` |

Las rutas van terminadas en NUL y rellenas con ceros hasta 9 bytes (`put_str` de libticalcs).
Estados de error (`FF xx`): `0A` no existe, `09` falta la carpeta, `0F`/`14` nombre no válido,
`15` falta `.tns`.

### Servicio de información `0x4020`

`02` → nombre del producto. `01` → 110 bytes: flash libre/total, RAM libre/total, batería,
versiones de OS/Boot/Boot2, pantalla y tipo de dispositivo (offsets de `get_version` en
`calc_nsp.cc`).

## Investigación del fallo intermitente (2026-11-13)

**Síntoma:** al conectar, `open` e `info` funcionan, pero el listado y las descargas dan
`timeout occured while reading from the device (errno = 11)` durante 20–60 s. Después funcionan
solos. Esa misma limitación tenía la primera versión con las descargas seguidas.

**Qué pasa en el cable** (registro de paquetes con `TCM_DEBUG=1`): la calculadora confirma con ACK
cada petición al servicio `0x4060`, pero no envía la respuesta. El servicio `0x4020` sigue
respondiendo. El enlace USB está bien; el servicio de archivos de la calculadora está «ocupado».

### Causas encontradas (cada una reproducida y luego eliminada)

| # | Causa | Prueba que la confirma |
|---|---|---|
| 1 | **Cambiar de servicio cerrando sesiones.** libticalcs se desconecta de `0x4060` y abre `0x4020` para `info` (y al revés). Después, el servicio de archivos deja de responder ~45 s. | En la misma conexión: `list` OK → `info` → `list` ocupado. Con `info` primero, igual. Con las dos subpeticiones (`01` y `02`). |
| 2 | **Paquetes de la propia calculadora sin atender.** Tras cada descarga, y en vez de la respuesta cuando el archivo no existe, la calculadora envía un paquete de 1 byte `02` desde un puerto nuevo a nuestro `0x4060`, y luego una desconexión desde `0x40DE`. libticalcs lo toma por la respuesta (`Invalid packet`) o lo confirma al puerto equivocado; la calculadora lo reenvía y se bloquea. | `get` OK → `list` = `Invalid packet` (TiLP/libticalcs y libnspire fallan igual). |
| 3 | **Pedir el documento abierto en la calculadora.** No hay respuesta y el servicio queda ocupado ~20–60 s. | `Ejemplos/P2.tns` falla siempre; confirmado que era el documento abierto. Los demás se descargan. |

### Hipótesis descartadas (no era eso)

| Hipótesis | Resultado |
|---|---|
| La calculadora necesita tiempo tras conectar | No: sin `info` previo, la primera petición responde a los 0,1 s de abrir, incluso tras 60 s sin conexión. |
| Secuencia de inicio incompleta (LOGIN) | libticalcs espera 4 s un LOGIN que esta OS no envía («OS = 1.1») y sigue; escuchando 60 s tras conectar no llega ningún paquete. |
| Timeout demasiado corto | No: con 30 s tampoco llega la respuesta; la calculadora no está tardando, no responde. |
| Reconexión (reset USB + dirección) | No desbloquea: el estado está en la calculadora. |
| Responder al paquete `02` con ACK, ignorarlo o sincronizar números de secuencia | Sin efecto. |
| Inactividad con el enlace abierto | No bloquea: un listado tras 60 s inactivo responde al instante. |

### Solución aplicada

1. **Un canal por servicio** (`0x4060` desde el puerto `0x8010`, `0x4020` desde `0x8011`), abierto
   en el primer uso y no se cierra hasta desconectar. Así ya no se alterna entre servicios con
   desconexiones de por medio.
2. **Recepción propia** (`chan_recv`/`wait_ack`): cada paquete recibido se clasifica como ACK nuestro,
   datos de nuestro canal o no solicitado. A los no solicitados se responde como Hackspire indica
   para la petición LOGIN del dispositivo (NACK desde `0x00D3`, datos `0x4050`), las desconexiones
   se confirman con ACK, y se sigue esperando la respuesta real.
3. Un error de la calculadora (`FF xx`, p. ej. «no existe») es una respuesta válida y **no cierra**
   el canal. Cerrar y reabrir justo después también provocaba ~45 s de bloqueo.
4. Si aun así una petición confirmada no recibe respuesta, el helper devuelve el código **9007
   (ocupada)**, distinto de `4` (sin respuesta del cable). La GUI explica la causa probable. En el
   listado de la raíz reintenta hasta 4 veces cada 20 s, con el estado visible y sin ocultar el
   error; *Actualizar* reintenta en el momento.

### Resultado (hardware real)

| Prueba | Antes | Después |
|---|---|---|
| `open → info → list` | ocupado ~45 s | OK (0,2 s) |
| `list → info → list → get → info → get` | ocupado tras `info` | todo OK |
| 2 descargas seguidas | 2.ª falla | OK; contenido idéntico byte a byte |
| `get` de un archivo inexistente | `Invalid packet` y bloqueo | error 1010 «no existe»; lo siguiente funciona |
| Reconexión tras 70 s sin enlace + `info` | ocupado | OK |
| GUI completa: conectar, listar, 2 descargas, expandir carpeta, almacenamiento | errores al inicio | OK en 8,4 s |
| Descargar el documento abierto (P2) | sin respuesta | sigue sin respuesta (limitación de la calculadora): error 9007 con explicación |

## Comandos de `tcm-link`

Petición: `id\tcomando\targ…\n`. Respuesta: una línea JSON con el mismo `id`.

| Comando | Qué hace | Probado con hardware |
|---|---|---|
| `hello` | versión del helper | sí |
| `probe` | PIDs USB de TI conectados, sin abrir enlace | sí |
| `open` / `close` | abre o cierra el enlace | sí |
| `info` | modelo, OS, flash libre/total, RAM, batería | sí |
| `list ruta` | contenido de una carpeta | sí |
| `get remota local` | descarga (escritura atómica `.part` + rename) | sí |
| `put local remota` | envío | **no** (no se permitieron escrituras) |
| `del`, `mkdir`, `rmdir`, `rename` | gestión | **no** (no se permitieron escrituras) |
| `listen segundos` | diagnóstico: muestra y atiende lo que la calculadora envía sola | sí |

Códigos de error: `4` sin respuesta del cable, `9007` petición confirmada sin respuesta (ocupada),
`1000 + xx` estado `FF xx` de la calculadora (`1010` = no existe), `266` paquete inesperado, `9001`
o más, errores locales del helper.

## Diagnóstico

- Registro del helper: `~/.local/state/texas-cas-manager/tcm-link.log` (siempre incluye los
  paquetes no solicitados atendidos).
- Registro de todos los paquetes: arrancar con `env TCM_DEBUG=1 ./scripts/run.sh`.

## Pendiente

- Probar `put`, `del`, `mkdir`, `rmdir` y `rename` con hardware, en una carpeta de pruebas y con
  autorización. Usan la misma capa de canales, pero no se han ejecutado nunca contra la calculadora.
