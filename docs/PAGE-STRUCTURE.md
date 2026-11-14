# Estructura de páginas y tipos de página

Muestra principal: `paginas.tns`, creado por el usuario en la calculadora (OS 4.5.5) con 6 páginas.
Copia local, **no está en Git**. Marcas: **[H]** comprobado · **[P]** hipótesis.

## Problemas y páginas **[H]**

```
Problem1.xml
<prob xmlns="urn:TI.Problem" ver="1.0" pbname="">
  <sym> <e t="6" f="0" c="255"><n>f1</n><p>x</p><v>x^2</v></e> </sym>   ← variables del problema
  <card clay="0" h1="10000" h2="10000" w1="10000" w2="10000">           ← página 1
    <isDummyCard>0</isDummyCard><flag>0</flag>
    <wdgt type="…" ver="…"> … </wdgt>
  </card>
  <card …> … </card>                                                     ← página 2…
</prob>
```

- **[H]** Las páginas no tienen identificador propio: su posición dentro de `ProblemN.xml` es su orden.
  `Document.xml` no guarda el número de páginas (`<nps>` es el número de problemas).
- **[H]** Las variables (`<sym>`) son del problema y las comparten todas sus páginas. La función de
  Gráficos y la lista `datos` se referencian por nombre.
- **[H]** Al reordenar las páginas (cada página se conserva byte a byte), la calculadora abre el
  documento con el nuevo orden y sigue funcionando
  ([HARDWARE-NATIVE-TESTS.md](HARDWARE-NATIVE-TESTS.md), prueba 3).
- **[H]** TIXC: este documento tiene más de 256 nombres de etiqueta distintos. A partir de ese punto,
  TI los escribe en forma literal y los cierra con `</nombre>`. El decodificador se corrigió para
  admitirlo; el XML resultante coincide con el CRC de TI.

## Tipos de página

| Aplicación | `wdgt type` | Contenido observado [H] |
|---|---|---|
| Notas | `TI.Notepad` 2.0 | `np:fmtxt` (ver [NOTES-FORMAT.md](NOTES-FORMAT.md)) |
| Lua | `TI.ScriptApp` 1.0 | `sc:script` en CDATA, `sc:guid`, `sc:md` |
| Calculadora | `TI.Scratchpad` 1.0 | `auth` (texto enriquecido) y una `erow` por entrada: `entr`/`exct` (entrada), `rslt` (`disp`, `full`, `warn2`: resultado guardado), `ctxt ang cplx comp` |
| Gráficos y Geometría | `TI.GeoGrapher` 1.0 (la misma para las dos) | `fig/objs`: `axes_system`, `axis`, `grid`, `label`, `camera3d`, `axes_3d`, `graph`, `expression` (Gráficos) o `line`, `number`… (Geometría), más `wdgt` hijos de interfaz |
| Listas y hojas de cálculo | `tabulator` 1.0 | `table/columns/column` (tipo, ancho, `formula`, `cells/cell` con `rowId`, `formula` y `data`), `functiontable` |
| Datos y estadísticas | `TI.DataGrapher` 1.0 | `DG_WIDGET`, `DG_GRAPH`, `DG_PLOT` (`PlotType2`), ejes y fuentes de datos |
| Python | — | sin muestras (la CX CAS no tiene Python) |

## Matriz de compatibilidad por tipo de página

| Aplicación | Detectado | Inspeccionable | Extraíble | Editable en local | Reconstruible | Verificado en calculadora |
|---|---|---|---|---|---|---|
| Notas: texto de fragmentos | sí | sí | sí (XML) | sí | sí | **sí** (Fase 4) |
| Notas: párrafos de texto (crear, borrar, reordenar, editar) | sí | sí | sí | sí, si el formato básico tiene contador centinela | sí | **sí** (Fase 5) |
| Notas: cuadros matemáticos | sí | sí (forma lineal y resultado) | sí | no | se conservan | conservados: sí |
| Lua | sí | sí | sí (`.lua`) | sí | sí | **sí** (Fase 4) |
| Calculadora | sí | entradas y resultados | sí (XML) | no | se conserva | — |
| Gráficos y Geometría | sí | tipos de objeto | sí (XML) | no | se conserva | — |
| Listas y hojas de cálculo | sí | columnas y fórmulas | sí (XML) | no | se conserva | — |
| Datos y estadísticas | sí | tipo de gráfico | sí (XML) | no | se conserva | — |
| Orden de páginas | — | — | — | sí | sí | **sí** (Fase 5) |
| Tipo desconocido | sí («desconocido») | XML | sí | no | se conserva | — |

## Operaciones sobre páginas

| Operación | Estado | Motivo |
|---|---|---|
| Reordenar | implementado y verificado en hardware | sin identificadores; cada página se copia byte a byte |
| Duplicar | no implementado | los widgets Lua llevan `sc:guid` (duplicarlo podría chocar), y los de Calculadora, Gráficos y Listas dependen de variables del problema con nombre (`f1`, `datos`) que se duplicarían o entrarían en conflicto. Sin pruebas en hardware |
| Eliminar | no implementado | otra página puede depender de las variables de la eliminada (Datos y estadísticas usa `datos`, definida en Listas) |
| Crear | no implementado | habría que generar desde cero el estado inicial de cada aplicación |
| Mover widgets entre páginas | no implementado | mismo problema de dependencias |
