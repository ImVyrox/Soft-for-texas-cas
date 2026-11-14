# Hoja de ruta y estado

Leyenda: ✅ implementado y probado · 🟡 implementado, sin probar con hardware · 🧪 experimental ·
🔍 pendiente de investigación · ⬜ pendiente

## Calculadora (USB)

| Función | Estado |
|---|---|
| Detección automática (USB `0451:e012`) | ✅ |
| Conexión e información (modelo, OS, almacenamiento, RAM, batería) | ✅ |
| Listado de carpetas con nombres reales | ✅ |
| Descargar archivos (también seguidas) | ✅ |
| Información sin bloquear el servicio de archivos | ✅ (canal propio por servicio) |
| Descargar el documento abierto en la calculadora | 🔍 la calculadora no responde; se informa con un error claro |
| Enviar archivos `.tns` | ✅ (SHA-256 verificado en `/TCM_TESTS`) |
| Borrar archivos | ✅ (con confirmación) |
| Borrar carpetas vacías | 🟡 |
| Crear carpetas, renombrar | ✅ |
| Arrastrar y soltar (ordenador ↔ calculadora, gestor de archivos → calculadora) | ✅ en modo demo; las operaciones de debajo, con hardware |
| Progreso de transferencias | ✅ |
| Captura de pantalla de la calculadora | ⬜ (libticalcs la ofrece: `ticalcs_calc_recv_screen`) |
| Backend libnspire / CX II | ⬜ |

## Documentos `.tns`

| Función | Estado |
|---|---|
| Analizar el contenedor y listar componentes | ✅ |
| Reescribir el contenedor idéntico byte a byte | ✅ |
| Extraer imágenes y componentes legibles | ✅ |
| Crear documentos Lua (idénticos a Luna 2.1) | ✅ |
| Editar el script Lua de documentos Luna o creados aquí | ✅ |
| Validar, comparar y guardar como versión nueva | ✅ |
| Abrir en la calculadora un documento generado | 🟡 |
| Leer el XML de documentos guardados por la calculadora | ✅ (Fase 3: cabecera TIEN0100 y TIXC) |
| Editar el script Lua de documentos nativos | ✅ probado en la calculadora (Fase 4) |
| Editar el texto de páginas de notas | ✅ probado en la calculadora (Fase 4) |
| Explorador interno, visor XML/imágenes, pestañas, buscar/reemplazar, autocompletado | ✅ |
| Editar cuadros matemáticos y otras páginas | 🔍 ver [EDITOR-ROADMAP.md](EDITOR-ROADMAP.md) |
| Documentos Python (CX II) | ⬜ |
| Añadir imágenes a documentos Lua | ⬜ (Luna sube la versión a `0700`) |

## Interfaz

| Función | Estado |
|---|---|
| Ventana principal, navegación, barra de estado, indicador USB | ✅ |
| Inicio, calculadora (2 paneles), archivos locales, editor, herramientas, configuración | ✅ |
| Tema claro / oscuro / sistema | ✅ |
| Notificaciones y animaciones discretas | ✅ |
| Editor Lua con números de línea y resaltado | ✅ |
| Buscar / reemplazar en el editor | ⬜ |

## Próximos pasos

1. Probar `rmdir` con hardware (requiere autorización).
2. Investigar si la calculadora puede entregar el documento que tiene abierto.
3. Comprobar en la calculadora un documento Lua generado y un nativo editado (requiere autorización).
4. Analizar una copia de `P2.tns` y documentos Python cuando haya muestras.
