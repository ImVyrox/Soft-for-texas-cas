# libnspire, TiLP (libticalcs) y alternativas

Investigación del 2026-11-13. Se clonó el código, se leyeron las cabeceras y se probaron ambas
bibliotecas con la calculadora real (solo operaciones de lectura).

## Opciones evaluadas

| | libticalcs2 (TiLP) | libnspire (Vogtinator) |
|---|---|---|
| Instalado en el sistema | sí: `libticalcs 1.1.9`, `libticables 1.3.5` (AUR, con TiLP 1.18) | no; existe `aur/libnspire-git` |
| Licencia | GPL-2.0+ | GPL-3.0+ |
| CX (`e012`) y CX II (`e022`) | sí | sí (CX II con su propio protocolo, `cx2.cpp`) |
| API de archivos por ruta | sí: `nsp_cmd_*` exportadas y con cabecera instalada (`tilp2/nsp_cmd.h`) | sí: `nspire_file_read/write/delete`, `nspire_dirlist`, `nspire_dir_create/delete`, `nspire_file_move/copy`, `nspire_attr` |
| Información del dispositivo | `ticalcs_calc_get_version` (modelo, OS, flash/RAM libres y totales, batería) | `nspire_device_info` (equivalente) |
| Progreso de transferencia | sí (`CalcUpdate.pbar`) | no |
| Probado aquí | info, listado y descarga: funcionan | compilada en local (sin instalar): info y 1.ª lectura funcionan |
| Problema tras una descarga | sí (ver USB-PROTOCOL.md) | sí, el mismo |

Nota: `nsp_cmd.h` avisa de que su compatibilidad hacia atrás «no se mantiene tan estrictamente»
como la de `ticalcs.h`. El helper se compila contra la versión instalada, y si cambia, se recompila.

## Decisión

Usar **libticalcs2 a través de un helper en C (`tcm-link`)**:

1. Ya está instalada y es la que usa TiLP en este equipo; no hace falta instalar nada.
2. Expone la API por rutas (`nsp_cmd_*`). Así se usan los nombres reales con extensión, sin la
   conversión nombre/tipo de `ticalcs_calc_get_dirlist`, que quita la extensión (`themes.csv` → `themes`).
3. Da progreso de transferencia.
4. Ejecutarla en un proceso aparte evita duplicar estructuras de C en Python (`CalcInfos`,
   `VarEntry`…), aísla los fallos de USB y no mezcla el bucle de glib con el de Qt.

### ¿Por qué no ctypes o cffi?

Se puede, pero `CalcInfos`, `VarEntry` y `CalcUpdate` habría que reproducirlos a mano en Python, y
un fallo de libusb tumbaría la GUI. Con un proceso aparte, la frontera es una línea JSON fácil de
probar con un helper falso (`tests/test_core.py`).

### libnspire como alternativa

La interfaz `Link` (`core/link.py`) permite añadir un backend de libnspire sin tocar la GUI. Sería
la opción para una **CX II**. No aporta nada para la CX CAS mientras siga el mismo bloqueo tras
las descargas. Para instalarla (requiere autorización, no se ha hecho):

```fish
yay -S libnspire-git
```

## Preparar el entorno (CachyOS / Arch)

Dependencias del sistema (ya presentes en este equipo):

```fish
pacman -Q libticalcs libticables libtifiles libticonv glib2 libusb   # comprobar
yay -S tilp            # si faltaran: instala libticalcs/libticables desde AUR
```

Las reglas udev (`/usr/lib/udev/rules.d/69-libticables.rules`, de libticables) ya dan acceso al
usuario con `uaccess`. No se necesita `sudo`.
