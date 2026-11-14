# Texas CAS Manager

Aplicación de escritorio para Linux que gestiona una calculadora **TI-Nspire CX CAS**: transferir
documentos por USB, explorar el contenido de los `.tns` y crear o editar documentos con scripts Lua.

> Nombre provisional. No es un producto de Texas Instruments ni está afiliado a TI.

## Calculadoras

| Modelo | Estado |
|---|---|
| TI-Nspire CX CAS (USB `0451:e012`), OS 4.5.5 | probado con hardware real |
| Otras TI-Nspire CX / CAS con USB `e012` | deberían funcionar (mismo protocolo), sin probar |
| TI-Nspire CX II (`e022`) | no soportado aún (libticalcs la detecta; falta probarla) |

## Funciones

Leyenda: ✅ implementado y probado · 🟡 implementado, sin probar con hardware · 🧪 experimental ·
🔍 pendiente de investigación

- ✅ Detección automática, modelo, versión del sistema, almacenamiento libre, RAM y batería.
- ✅ Explorador de archivos de la calculadora (nombres reales, tamaños, búsqueda, orden).
- ✅ Descarga de documentos con progreso, también varias seguidas. El documento que está abierto en
  la calculadora no se puede descargar: hay que cerrarlo antes (ver
  [docs/USB-PROTOCOL.md](docs/USB-PROTOCOL.md)).
- ✅ Envío de `.tns`, crear carpetas, renombrar y borrar archivos (con confirmación), probados con
  hardware en una carpeta de pruebas ([docs/HARDWARE-TESTS.md](docs/HARDWARE-TESTS.md)). 🟡 Borrar
  carpetas, sin probar.
- ✅ Arrastrar y soltar entre el ordenador y la calculadora (probado en modo demo).
- ✅ Análisis de `.tns`: versión, componentes, codificación, CRC, reescritura idéntica.
- ✅ Extracción de componentes legibles (imágenes, script Lua).
- ✅ Creación de documentos Lua, idénticos byte a byte a los de [Luna](https://github.com/ndless-nspire/Luna) 2.1.
- ✅ Edición del script Lua (resaltado de sintaxis) de documentos creados por Luna o por este programa.
- ✅ Reconstrucción validada, comparación con el original y guardado como versión nueva. El
  original nunca se modifica.
- 🔍 El XML de los documentos **guardados por la propia calculadora** está cifrado con claves no
  documentadas: se muestran y conservan sus componentes, pero no se pueden leer ni editar.
- ✅ Gestor de archivos locales: abrir, duplicar, renombrar, papelera, importar, exportar recursos.
- ✅ Tema claro y oscuro, notificaciones y modo demostración sin USB.

Estado detallado: [docs/ROADMAP.md](docs/ROADMAP.md).

## Instalación (CachyOS / Arch Linux)

Dependencias del sistema: `libticalcs`, `libticables`, `libtifiles`, `libticonv` (vienen con TiLP
desde AUR), `glib2`, `libusb`, `gcc` y `pkg-config`. Las reglas udev de libticables dan acceso al
USB sin `sudo`.

```fish
git clone git@github.com:ImVyrox/Soft-for-texas-cas.git
cd Soft-for-texas-cas
uv venv .venv          # o: python -m venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
./scripts/build-helper.sh
./scripts/run.sh
```

Dependencias de Python: `PySide6` y `pycryptodome` (para el cifrado 3DES de los documentos).

## Uso

1. Conecta la calculadora por USB, enciéndela y déjala en la pantalla de inicio.
2. La aplicación la detecta sola (indicador arriba a la derecha).
3. **Calculadora**: arrastra `.tns` del panel izquierdo al derecho para enviarlos, o al revés para
   descargarlos.
4. Si un documento no se descarga y aparece «ocupada», ciérralo en la calculadora: no entrega el
   documento que tiene abierto.
5. **Editor .tns**: abre un documento, edita el script Lua, pulsa *Validar* o *Comparar* y luego
   *Guardar como nueva versión*.

## Documentación

- [Arquitectura](docs/ARCHITECTURE.md)
- [Comunicación USB](docs/USB-PROTOCOL.md)
- [libnspire, TiLP y alternativas](docs/LIBNSPIRE.md)
- [Formato .tns](docs/TNS-FORMAT.md)
- [Desarrollo y pruebas](docs/DEVELOPMENT.md)
- [Pruebas con hardware real](docs/HARDWARE-TESTS.md)

## Licencia

MIT (ver [LICENSE](LICENSE)). `src/texas_cas_manager/tns/_luna_data.py` contiene constantes de
Luna y está bajo la Mozilla Public License 1.1. El helper USB enlaza con libticalcs2 (GPL-2.0+).
