# Páginas de notas y contenido matemático

Muestras (copias locales, **no están en Git**):
- `potenciales.tns`: 4 páginas de notas; la primera tiene una imagen y las otras 3 están vacías.
- `Documento1.tns`: creado por el usuario en la calculadora (OS 4.5.5) para esta investigación, con
  2 páginas de notas con texto, `π` y cuadros matemáticos.

Las pruebas automáticas usan un documento sintético con la misma estructura
(`tests/native_fixture.py`).

Marcas: **[H]** comprobado en las muestras · **[P]** hipótesis.

## Páginas

- **[H]** Un `ProblemN.xml` (`<prob xmlns="urn:TI.Problem">`) contiene un `<card>` por página. Cada
  `<card>` lleva un `<wdgt type="…">` con la aplicación de la página.
- **[H]** Tipos vistos: `TI.Notepad` (notas) y `TI.ScriptApp` (Lua).
- **[P]** Otros tipos (calculadora, gráficos, geometría, listas): no hay muestras. El usuario creó
  `Documento1.tns` con notas solamente, así que aún no se han podido estudiar.
- **[H]** `<sym>` del problema contiene las variables (`<e><n>nombre</n><v>valor</v></e>`).

## Notas (`TI.Notepad`, ver. 2.0)

```
<wdgt xmlns:np="urn:TI.Notepad" type="TI.Notepad" ver="2.0">
  <np:mFlags>…</np:mFlags><np:value>3</np:value>
  <np:fmtxt> …XML escapado… </np:fmtxt>
</wdgt>
```

**[H]** `np:fmtxt` contiene un documento XML completo, escapado como texto (`&lt;` `&gt;` `&quot;`):

```
<r2dtotree version="1">
  <formatManager tableSize="N" capacity="10">
    <formatEntry entryIndex="i" entryID="i" entryRefCnt="n" tc=… fc=… fs=… fst=… cc=… fn0="TI-Nspire"…/>
  </formatManager>
  <node name="1doc">
    <node name="1para">                       ← párrafo
      <node name="1rtline">                   ← línea
        <leaf name="1word" np="1" id0="F" pp0="L">texto</leaf>
        <node name="0el" flags="8" id0="1"> … cuadro matemático … </node>
        <leaf name="1widgetNode" …><wdgt type="Image">…</wdgt></leaf>
```

| Elemento | Qué se sabe |
|---|---|
| `formatEntry` | **[H]** tabla de formatos: color (`tc`), tamaño (`fs`), estilo (`fst`), fuente (`fn0`). `entryRefCnt` = número de referencias `id0` a ese formato (comprobado en los 3 formatos usados de `Documento1`); la entrada 0 lleva `2147483647` |
| `1word` | **[H]** fragmento de texto. `np` = número de tramos de formato; `id0` = formato; `pp0` = longitud en **caracteres** (`hola` → 4, `π` → 1). Un fragmento vacío lleva `pp0="0"`; el que tiene el cursor contiene `<cursor index="0"/>` |
| `0el flags="8"` con `<mbox>` | **[H]** cuadro matemático: `<attr …>` (modo, dígitos, `comp`…), `<out><full>resultado</full><warn>{}</warn><err>0</err></out>` y dos `0el` con `0text`: la entrada y la salida (`readonly="1"`) |
| `1widgetNode` + `<wdgt type="Image">` | **[H]** imagen incrustada. `<name>` = nombre de la entrada BMP del contenedor (así se relaciona la página con el recurso); también tamaño, recorte, escala y una ruta de Windows del equipo donde se creó |
| Expresiones matemáticas | **[P]** el texto de la entrada aparece como `0text` (en la muestra, `4`); no hay muestras con fracciones, potencias o plantillas |

## Qué se puede modificar sin corromper el documento

- **Comprobado en hardware:** el texto de fragmentos `1word` ya existentes, con `np="1"`, sin
  elementos hijos, actualizando `pp0`. Incluye `ñ` y vocales con tilde
  ([HARDWARE-NATIVE-TESTS.md](HARDWARE-NATIVE-TESTS.md)).
- **No habilitado** (sin pruebas que lo respalden):
  - añadir o quitar fragmentos o párrafos;
  - cambiar formatos;
  - fragmentos con varios tramos de formato;
  - caracteres fuera del conjunto permitido (`< > & "`, otros alfabetos);
  - los cuadros matemáticos: su resultado está en caché (`<out><full>`) y cambiar la entrada lo
    dejaría desincronizado;
  - las imágenes.

## Cómo edita el programa (`tns/notes.py`)

1. Se localiza el `np:fmtxt` de la página y, dentro, el n-ésimo `1word` del texto escapado.
2. Se sustituyen solo su texto y su `pp0`; el resto de bytes queda igual.
3. Se vuelve a leer el XML y se exige que la página conserve el mismo número de fragmentos, cuadros
   matemáticos, imágenes y párrafos, el mismo formato en cada fragmento, y el texto nuevo solo en
   los fragmentos editados.
4. La entrada se recodifica y se cifra con su propia cabecera (`tns/xmlentry.py`).
