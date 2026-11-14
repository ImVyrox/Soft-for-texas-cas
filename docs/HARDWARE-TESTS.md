# Pruebas con hardware real

## 2026-11-13 — escritura en `/TCM_TESTS` (autorizada)

- **Calculadora:** TI-Nspire CX CAS, OS 4.55.0079 (como lo informa libticalcs), USB `0451:e012`.
- **Helper:** `tcm-link` del commit `ba05b2d` + este commit.
- **Script:** `scripts/hardware_write_test.py`. Se puede repetir; antes conviene ensayarlo con `--mock`.
- **Alcance autorizado:** solo la carpeta `/TCM_TESTS`. Antes de cada escritura, el script comprueba
  que la ruta normalizada es `/TCM_TESTS` o está directamente dentro de ella (pruebas en
  `tests/test_hw_script.py`). Se detiene al primer fallo y no repite escrituras.

### Archivo de prueba

Documento Lua generado localmente con `build_lua_document`. No es un documento personal.
`tcm_prueba.tns`, 911 bytes, SHA-256
`964d63e290e64a18371f7246338ee5b4b51b80851c3930edee2b4f0341dcaf9e`.

### Operaciones

| # | Operación | Qué se ejecutó | Respuesta de la calculadora | Verificación | Resultado |
|---|---|---|---|---|---|
| 1 | Crear carpeta | `mkdir /TCM_TESTS` (comando `0A 03 ruta`) | `FF 00` (éxito), 0,27 s | Listado de `/`: `/TCM_TESTS` aparece como carpeta (tipo 1) | ✅ |
| 2 | Enviar archivo | `put tcm_prueba.tns → /TCM_TESTS/tcm_prueba.tns` (`03 01 ruta tamaño`, `04`, `05 contenido`) | `04` y luego `FF 00`; 911 bytes, 1,19 s | Ver paso 3 | ✅ |
| 3 | Verificar listado | `list /TCM_TESTS` | 1 entrada: `tcm_prueba.tns`, 911 bytes | El tamaño coincide con el archivo local (911) | ✅ |
| 4 | Descargar de nuevo | `get /TCM_TESTS/tcm_prueba.tns` | `03 01 …` + contenido, 911 bytes, 0,26 s | Ver paso 5 | ✅ |
| 5 | Comparar SHA-256 | SHA-256 del original y del descargado | — | Los dos dan `964d63e2…dcaf9e`; además el descargado se analiza como `.tns` válido con su script Lua legible | ✅ |
| 6 | Renombrar | `rename /TCM_TESTS/tcm_prueba.tns → /TCM_TESTS/tcm_prueba_renombrada.tns` (`21 01 ruta ruta2`) | `FF 00` (éxito), 0,18 s | Ver paso 7 | ✅ |
| 7 | Verificar nombre | `list /TCM_TESTS` | 1 entrada: `tcm_prueba_renombrada.tns`, 911 bytes | El nombre nuevo está y el antiguo no | ✅ |
| 8 | Eliminar archivo de prueba | `del /TCM_TESTS/tcm_prueba_renombrada.tns` (`09 01 ruta`) | `FF 00` (éxito), 0,19 s | Ver paso 9 | ✅ |
| 9 | Verificar eliminación | `list /TCM_TESTS` | 0 entradas | `/TCM_TESTS` queda vacía | ✅ |

`/TCM_TESTS` se conserva en la calculadora, vacía.

### Integridad de los archivos personales

Antes y después de las operaciones se tomó una instantánea de solo lectura: listado recursivo de
todo menos `/TCM_TESTS`, y descarga + SHA-256 de cada archivo que la calculadora entrega.

| Elemento | Tamaño | SHA-256 (antes = después) |
|---|---|---|
| `/potenciales.tns` | 7916 | `1de7a987…d853b575` (igual que en una descarga de 1,5 h antes) |
| `/MyWidgets/stopwatch.tns` | 16772 | `7c80464e…fd6f5df7` |
| `/themes.csv` | 191 | `7805140f…2c2ec6f2` |
| `/Ejemplos/P2.tns` | 36847 | solo listado: es el documento abierto y la calculadora no lo entrega |
| `/NspireLogs.zip` | 0 | solo listado: la calculadora no responde al pedirlo (archivo del sistema) |
| `/Ejemplos`, `/MyLib`, `/MyLib/Ejemplos`, `/MyWidgets` | carpetas | igual |

Resultado: las 9 entradas coinciden exactamente (nombre, tipo, tamaño y hash). No se tocó nada
fuera de `/TCM_TESTS`.

### Incidencias

1. **Primer intento, detenido antes de escribir nada.** La instantánea previa pidió
   `/NspireLogs.zip` y la calculadora lo confirmó pero no respondió (error 9007). Siguiendo las
   condiciones, el script se detuvo. Como no se había hecho ninguna escritura, tras esperar a que el
   servicio se liberara (~75 s) se repitió la ejecución con ese archivo comparado solo por listado.
   No se repitió ninguna operación de escritura.
2. **Paquetes no solicitados.** El helper atendió 7 pares (`02` + desconexión), uno por cada
   descarga (3 + 3 de las instantáneas y 1 del paso 4). Crear carpeta, enviar, renombrar y borrar
   no generan ninguno.

### No probado

`rmdir` (borrar carpeta): no estaba en las operaciones autorizadas.
