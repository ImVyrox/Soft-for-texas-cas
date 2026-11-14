# Hoja de ruta y estado

Leyenda: ✅ implementado y probado · 🟡 implementado, sin probar con hardware · 🧪 experimental ·
🔍 pendiente de investigación · ⬜ pendiente

## Calculadora (USB)

| Función | Estado |
|---|---|
| Detección automática (USB `0451:e012`) | ✅ |
| Conexión e información (modelo, OS, almacenamiento, RAM, batería) | ✅ |
| Listado de carpetas con nombres reales | ✅ |
| Descargar un archivo | ✅ (la primera descarga de cada sesión) |
| Descargas seguidas | 🧪 la calculadora deja de responder tras una descarga; hay reintento y resync (ver USB-PROTOCOL.md) |
| Enviar archivos `.tns` | 🟡 |
| Borrar archivos / carpetas vacías | 🟡 (con confirmación) |
| Crear carpetas, renombrar | 🟡 |
| Arrastrar y soltar (ordenador ↔ calculadora, gestor de archivos → calculadora) | ✅ en modo demo / 🟡 con hardware |
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
| Leer el XML de documentos guardados por la calculadora | 🔍 clave de cifrado no documentada |
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

1. Confirmar qué muestra la calculadora tras una descarga y resolver el bloqueo.
2. Probar envío, borrado y carpetas con hardware en una carpeta de pruebas.
3. Comprobar en la calculadora un documento Lua generado por el programa.
4. Buscar documentación sobre la derivación de claves de las cabeceras cifradas.
