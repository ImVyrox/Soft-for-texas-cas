# Cuadros matemáticos

Muestra: `mates.tns`, creado por el usuario en la calculadora (OS 4.5.5): una página de notas con un
cuadro matemático por línea. Copia local, **no está en Git**; las pruebas usan las mismas
estructuras en `tests/native_fixture.py`. Marcas: **[H]** comprobado · **[P]** hipótesis.

## Estructura

```
<node name="0el" flags="8" id0="1">                ← cuadro matemático dentro de un párrafo de notas
  <mbox>
    <attr iomode="1" digits="0" angle="0" symbol="1" wrap="true" warn="true" comp="2" active="true" id0="3"/>
    <out><full>5/6</full><warn>{}</warn><err>0</err></out>     ← resultado guardado por TI
  </mbox>
  <node name="0el" id0="2"> …entrada… </node>
  <node name="0el" id0="3"> …salida mostrada (readonly="1")… </node>
</node>
```

| Campo | Estado | Qué se sabe |
|---|---|---|
| Entrada (primer `0el`) | **comprendido [H]** | árbol de `0text` y plantillas; es lo que escribió el usuario |
| `<out><full>` | **comprendido [H]** | resultado en forma lineal calculado por TI (`5/6`, `√(2)`, `x^3`, `[[1,2][3,4]]`, `2*a`) |
| `<out><err>` | **comprendido [H]** | 0 sin error; en la integral, `140`, y la salida es un `0mline` con el mensaje («Error: El argumento debe ser un nombre de variable.») |
| `<out><warn>` | parcial | `{}` en todas las muestras |
| Salida mostrada (segundo `0el`, `readonly="1"`) | **comprendido [H]** | el resultado como árbol 2D (fracción `5`/`6`, raíz, potencia, matriz) |
| `attr` (`iomode`, `digits`, `angle`, `symbol`, `wrap`, `warn`, `comp`, `active`) | parcial | `comp="2"` en cajas evaluadas y `comp="1"` en la caja vacía; el resto, igual en todas las muestras |
| `wped="1"` | desconocido | solo en la caja con error |
| `id0` de los `0el` / `0text` | parcial | índices de formato del `formatManager` de la página. En `Documento1` los contadores cuadraban; en `mates.tns` hay índices (5–8) de entradas que no se vieron en la tabla: sin explicar |

### Plantillas (nodos de la entrada y de la salida) **[H]**

| Nodo | Partes (`0el` hijos) | Ejemplo | Forma lineal que muestra el programa |
|---|---|---|---|
| `0fraction` | 2 (numerador, denominador) | 1/2 | `(1)/(2)` |
| `0sqrt` | 1 | √2 | `√(2)` |
| `0power` | 1 (exponente; la base es el texto anterior) | x³ | `x^(3)` |
| `0integral` | 4, guardadas como inferior, superior, integrando, variable (una sola muestra) | ∫ de 0 a 1 de x² dx | `∫(x^(2),x,0,1)` |
| `0matrix` `data="C"` | filas × C | [[1,2][3,4]] | `[[1,2][3,4]]` |
| `0mline` | 1 | mensaje de error | `"…"` |

- **[H]** En los fragmentos con varios formatos (`np="2"`, `np="3"`), los `ppN` son posiciones finales
  **acumuladas**: en `a=2`, `id0=6 pp0=1, id1=2 pp1=3`.
- **[H]** La entrada `a*2` se guardó con el resultado `2*a`.
- **[H]** Las variables definidas aparecen en `<sym>` del problema solo en algunos casos (`paginas.tns`:
  `f1`). En `mates.tns`, `a=2` es una comparación, no una definición.

## Qué hace el programa

- **Lectura (implementado):** `tns/mathbox.py` reconstruye la forma lineal de la entrada a partir del
  árbol y muestra el resultado guardado y el código de error. Las plantillas no reconocidas o con
  un número de partes inesperado se marcan «desconocido».
- **Edición: no se ofrece.** La entrada y el resultado se guardan por separado, y el resultado lo
  calcula el motor de TI. Cambiar la entrada dejaría `<out>` y la salida 2D desactualizados.
  Inventar el resultado no es aceptable, y borrarlo para que TI lo recalcule no está probado.

## Investigación pendiente

| Pregunta | Cómo comprobarlo |
|---|---|
| ¿Recalcula TI una caja si su `<out>` y su salida están vacíos? La caja vacía de las muestras tiene `<out><err>0</err></out>` y `comp="1"` | Prueba en hardware: una copia con una entrada cambiada y `<out>` vaciado, en `/TCM_TESTS` y con autorización |
| ¿Qué significan los índices `id0` que no están en la tabla de formatos? | Más muestras con estilos distintos |
| Otras plantillas (derivada, sumatorio, límite, valor absoluto, sistemas) | Muestra con esas plantillas |
