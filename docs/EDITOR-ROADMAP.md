# Hoja de ruta del editor

Leyenda: ✅ hecho (prueba automática) · 🔩 hecho y probado en hardware · ⬜ pendiente ·
🔍 falta investigación o muestras

## Hecho en la Fase 4

| Área | Función | Estado |
|---|---|---|
| Documentos nativos | Editar el script Lua y reconstruir con la cabecera original | 🔩 |
| Notas | Ver páginas: texto, cuadros matemáticos, imágenes | ✅ |
| Notas | Editar el texto de fragmentos existentes | 🔩 |
| Interfaz | Explorador de páginas con estado (editable / solo lectura / desconocido / protegido) | ✅ |
| Interfaz | Tabla de contenido de la página; propiedades; historial de operaciones | ✅ |
| Interfaz | Vista previa de cambios (diferencias de scripts, notas y XML) | ✅ |
| Lua | Navegador de funciones | ✅ |
| Lua | Plegado de bloques (`function`/`do`/`then`/`repeat` … `end`/`until`) desde el margen | ✅ |
| Lua | Errores de sintaxis mientras se escribe (`luac5.1`, en segundo plano) | ✅ |
| Lua | Avisos de APIs no disponibles en TI-Nspire (`io`, `os`, `debug`, `file`, `dofile`, `loadfile`, `module`) | ✅ |
| Lua | Formatear: solo se aplica si `luac5.1 -s` produce el mismo bytecode; respeta la sangría del script | ✅ |
| Lua | Buscar y reemplazar con regex (grupos `\1`) y palabra completa | ✅ |

## Hecho en la Fase 5

| Área | Función | Estado |
|---|---|---|
| Notas | Crear, eliminar, reordenar y editar párrafos de texto | 🔩 |
| Páginas | Reordenar páginas | 🔩 |
| Matemáticas | Lectura en forma lineal, resultado, error, plantillas desconocidas | ✅ (solo lectura) |
| Otras páginas | Resúmenes de Calculadora, Gráficos/Geometría, Listas, Datos; variables del problema | ✅ (solo lectura) |
| TIXC | Más de 256 nombres de etiqueta (forma literal) | ✅ (comprobado con el CRC de TI) |
| Interfaz | Vista de página por párrafos; Deshacer/Rehacer de ediciones de páginas | ✅ |

## Lua en TI-Nspire: estándar frente a TI

Fuente: [TI-Nspire Lua Scripting API Reference Guide](https://education.ti.com/html/webhelp/EG_TINspireLUA/EN/content/eg_splash_page/splash_luaapiguide.htm).

| Aspecto | Qué hace el editor |
|---|---|
| Lua 5.1 | La sintaxis se comprueba con `luac5.1` |
| No disponibles: `file`, `io`, `os`, `debug`, `dofile`, `loadfile`, `module` (guía de TI, «Unimplemented libraries and functions») | Aviso en la línea; no se sugieren |
| `require` solo carga librerías de TI; no admite librerías propias (guía de TI, «Module Library») | Sin autocompletado específico |
| APIs de TI: eventos `on.*`, `gc:*`, `platform.*`, `timer.*`, `var.*`, `image`, `cursor`, `toolpalette`, `D2Editor`, `class` | En el autocompletado solo las de uso habitual que aparecen en la guía |
| `platform.apiLevel` (por ejemplo `'2.0'`) cambia el comportamiento de algunas funciones | No se comprueba |

## Pendiente

| Función | Por qué no está |
|---|---|
| Editar cuadros matemáticos | El resultado va en caché en `<out>`; falta probar en hardware si TI lo recalcula con `<out>` vacío. 🔍 |
| Duplicar, eliminar o crear páginas | Dependencias por variables (`f1`, `datos`) y `sc:guid` (ver [PAGE-STRUCTURE.md](PAGE-STRUCTURE.md)). 🔍 |
| Editar Calculadora, Gráficos, Listas | Los resultados también se guardan en caché; requieren el motor de TI. 🔍 |
| Párrafos en documentos del software de TI 6.3 | El formato 0 cuenta referencias: habría que actualizar los contadores. 🔍 |
| Vista previa renderizada de la página | Requiere interpretar formatos y fuentes de TI. ⬜ |
| Autocompletado completo de la API de TI | Hay que transcribir la guía con cuidado. ⬜ |
| Plegado de tablas y comentarios largos | Solo se pliegan bloques de código. ⬜ |
| Documentos con varios problemas en hardware | Probado solo en local. ⬜ |
