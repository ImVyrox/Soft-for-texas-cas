# Comunicación USB con la TI-Nspire

Estado: investigado y probado con hardware real el 2026-11-13 (TI-Nspire CX CAS,
OS 4.5.5.79, Boot2 4.5.0.14, USB `0451:e012`, CachyOS, libticalcs2 1.1.9).

## Capas

```
GUI (PySide6) ── LinkService (un hilo de trabajo) ── HelperLink ──stdin/stdout JSON──▶ tcm-link (C)
                                                                                        │
                                                                                 libticalcs2 / libticables2 / libusb
```

`tcm-link` (`native/tcm-link/tcm_link.c`) es un proceso hijo. Si libusb o libticalcs
se cuelgan o fallan, la GUI sigue viva y puede relanzarlo.

## Protocolo de la calculadora (NavNet)

Datos tomados del código de libticalcs (`calc_nsp.cc`, `nsp_cmd.cc`, `nsp_vpkt.cc`),
de libnspire (`services/file.c`, `data.c`, `packet.c`) y de la página
[USB Protocol de Hackspire](https://hackspire.org/index.php/USB_Protocol).

- Paquetes de hasta 254 bytes de datos. Los trozos de archivo son de 253 bytes (1 byte de comando).
- Direcciones: ordenador `0x6400`, calculadora `0x6401`. Antes de nada, la calculadora pide una
  dirección (`0x4003`) tras un reset USB.
- Cada paquete se confirma con un ACK (puerto origen `0x00FF`, `AK=0x0A`, datos = puerto que lo recibió).
  Un NACK usa el puerto origen `0x00D3`.
- Servicios: `0x4020` información del dispositivo, `0x4060` gestión de archivos, `0x40DE` desconexión.

### Servicio de archivos `0x4060` (comandos usados)

| Operación | Comando | Respuesta |
|---|---|---|
| Listar carpeta | `0D ruta` / `0E` (siguiente) / `0F` (fin) | `10` por entrada: nombre, tamaño, tipo (0 archivo, 1 carpeta) |
| Descargar | `07 01 ruta` → `04` | `03 01 … tamaño`, luego trozos `05 …`; el ordenador cierra con `FF 00` |
| Enviar | `03 01 ruta 00 tamaño` → trozos `05 …` | `FF 00` (éxito) o `FF xx` (error) |
| Borrar archivo | `09 01 ruta` | estado |
| Crear / borrar carpeta | `0A` / `0B` | estado |
| Renombrar / mover | `21 origen destino` | estado |

Las rutas son absolutas y llevan la extensión real (`/Ejemplos/P2.tns`). La calculadora solo
acepta documentos `.tns` al enviar (error `FF 15` sin extensión).

## Comandos de `tcm-link`

Petición: `id\tcomando\targ…\n`. Respuesta: una línea JSON con el mismo `id`.

| Comando | Qué hace | Probado con hardware |
|---|---|---|
| `hello` | versión del helper | sí |
| `probe` | PIDs USB de TI conectados, sin abrir enlace | sí |
| `open` / `close` | abre o cierra el enlace (`ticalcs_calc_isready`) | sí |
| `info` | modelo, OS, flash libre/total, RAM, batería | sí |
| `list ruta` | contenido de una carpeta | sí |
| `get remota local` | descarga (escritura atómica `.part` + rename) | sí, con la limitación de abajo |
| `put local remota` | envío | **no** (sin probar con hardware) |
| `del`, `mkdir`, `rmdir`, `rename` | gestión | **no** (sin probar con hardware) |
| `resync` | reset USB + asignación de dirección | sí |

Errores: `{"ok":false,"code":N,"error":"…"}` con el texto de libticalcs/libticables
(p. ej. `404` no existe, `4` timeout). Progreso: `{"event":"progress","done":N,"total":N}`.

## Limitación encontrada: la calculadora deja de responder tras una descarga

Observado y reproducido el 2026-11-13 en OS 4.5.5:

1. La primera descarga funciona (por ejemplo `/potenciales.tns` en 0,3 s).
2. Al cerrar la sesión, la calculadora envía un paquete propio: desde un puerto nuevo, al puerto
   `0x4060` del ordenador, con 1 byte `0x02`. libticalcs lo llama «martian» y lo ignora.
3. A partir de ahí el servicio `0x4060` confirma (ACK) cada petición, pero no la responde.
   El servicio de información (`0x4020`) sigue funcionando.

Pruebas realizadas, todas con el mismo resultado:

| Variante | Resultado |
|---|---|
| libticalcs de alto nivel (`ticalcs_calc_recv_var2` dos veces, como TiLP) | 2.ª descarga: `Invalid packet` (266) |
| libnspire (compilada en local) | 2.ª lectura: `Timeout` |
| tcm-link, ignorar el paquete | `Invalid packet` |
| tcm-link, responder con ACK | timeout |
| tcm-link, responder con NACK (como hace libnspire) | timeout |
| tcm-link, reset USB + asignación de dirección | timeout las primeras veces; una vez se recuperó a los ~20 s |

Una vez el servicio se recuperó solo, pero en otra prueba siguió bloqueado varios minutos. Por eso
se sospecha que la calculadora muestra algo en pantalla tras la transferencia (pendiente de
confirmar mirando la calculadora).

Medidas en el código:

- `tcm-link` hace `resync` tras cada descarga.
- `HelperLink` reintenta (con `resync`) una operación de archivos que da timeout justo después de
  una descarga, hasta `busy_retry_seconds` (60 s).
- La GUI encadena las transferencias de una en una y muestra el error si al final falla.

**Pendiente:** confirmar qué muestra la pantalla de la calculadora después de una descarga y
probar `put`, `del`, `mkdir`, `rmdir` y `rename` con hardware.
