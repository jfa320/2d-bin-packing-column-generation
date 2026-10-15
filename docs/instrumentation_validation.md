# Validación del registro por iteración

La instrumentación permite distinguir preparación/construcción de solve,
consultar cada intento de CG y calcular porcentajes por instancia sin ampliar
el CSV principal de 24 columnas. El detalle se exporta en
`*_iterations.csv` y `*_phases.csv`; `--detailed-csv` conserva el diagnóstico
final de 44 columnas. La traza PAVER mantiene ocho columnas.

## Verificación funcional

Las pruebas con reloj controlado cubren:

- Construcción inicial imputada a la primera fila, actualizaciones y rebuild.
- Tiempos puros de `model.solve()`, sin incluir publicación del checkpoint,
  extracción de duales ni mapeo de solución.
- Segunda fase y pricing auxiliares incluidos en la misma iteración.
- Numeración creciente después de un retry exitoso, sin reutilizar objetivos
  o estados de la fila anterior.
- Cuatro tipos de componente interrumpido: build/solve de master/pricing.
- Conservación de filas cerradas y extensión únicamente de la fila activa
  hasta el corte del padre, excluyendo el cierre del proceso.
- Errores de segunda fase y postprocesamiento, conservando el estado CPLEX
  ya reportado cuando corresponde.
- Transporte de una fila cerrada por evento, sin reenviar todo el historial.
- Porcentajes sobre total y CG, denominadores nulos, protección de archivos
  y compatibilidad de los reportes 24/44 y PAVER.

Se ejecutaron 350 pruebas enfocadas. La verificación real de CPLEX en case1
incluye flujo base, heurísticas, proceso hijo, ambos formatos CSV, los archivos
adicionales y factibilidad geométrica. No equivale a ejecutar toda la suite,
que incluye solves grandes.

También se ejecutó el runner completo con proceso hijo, layout y exportación
en case1, IB_001, IB_002 e IB_003, con 15 s por instancia y 90 s externos.
Las cuatro corridas terminaron normalmente, coincidieron con las referencias
4/5/10/15 y produjeron 6/10/25/31 filas de iteración (72 en total). Se verificaron
numeración, tamaño del pool, columnas aceptadas, sumas de tiempos y las doce
columnas de porcentajes contra sus denominadores.

| Instancia | Master / CG (%) | Pricing / CG (%) | Pricing / total (%) |
|---|---:|---:|---:|
| case1 | 24.444313 | 70.043812 | 5.623761 |
| IB_001 | 20.706876 | 76.014888 | 10.753610 |
| IB_002 | 8.858940 | 89.929422 | 48.312934 |
| IB_003 | 4.045370 | 95.507033 | 75.360722 |

Son observaciones individuales del pipeline completo, distintas de las medianas
del experimento aislado de abajo. Los agregados incluyen construcción, solve
y postprocesamiento/bookkeeping; la exportación del layout e inicio/cierre del
proceso afectan el denominador total.

Artifacts locales:

- `Results/instrumentation_validation_input_20261012_225014_860.csv`.
- `Results/instrumentation_validation_20261012_225014_860.csv` (24 columnas).
- `Results/instrumentation_validation_20261012_225014_860_iterations.csv` (35 columnas).
- `Results/instrumentation_validation_20261012_225014_860_phases.csv` (25 columnas).

## Costo adicional del historial

Medición local del 12/10/2026 con Python 3.10.4 y CPLEX 22.1.1.0:

- Cuatro instancias completas, tres repeticiones por modo y un calentamiento.
- Orden alternado de `record_iterations=False` y `True`.
- Procesos aislados, límite CPLEX de 15 s y límite externo de 25 s por corrida.
- Comparación solo de pares con terminación normal y coincidencia de valores
  LP/IP, iteraciones, columnas, motivo de parada y convergencia registrada.
- Ambos modos mantienen temporizadores y snapshots. La cola descarta los
  snapshots inmediatamente, evitando un backlog artificial.
- El tiempo del worker excluye inicio/importación del proceso, IPC, layout
  y escritura CSV. Por tanto se mide el costo adicional de construir/retener
  el historial, no el costo total de toda la instrumentación o exportación.
- La coincidencia de descriptores finales no prueba identidad de todas las
  columnas o estados intermedios de la trayectoria.

### Resultados de tiempo CG

| Instancia | Pares comparables | Mediana sin historial (s) | Mediana con historial (s) | Diferencia (s) | Diferencia (%) | Rango de diferencias pareadas (s) |
|---|---:|---:|---:|---:|---:|---|
| case1 | 3 | 0.083772 | 0.091955 | +0.008183 | +9.77 | -0.004887 a +0.009342 |
| IB_001 | 3 | 0.154265 | 0.161497 | +0.007232 | +4.69 | -0.031474 a +0.049395 |
| IB_002 | 3 | 1.033447 | 1.009096 | -0.024352 | -2.36 | -0.327284 a +0.879407 |
| IB_003 | 3 | 4.003738 | 4.313316 | +0.309578 | +7.73 | -0.769393 a +1.247878 |

Todos los rangos cruzan cero. Esta muestra contiene ruido suficiente para
impedir afirmar que el costo es despreciable o que una diferencia negativa
representa una mejora. Se documentan las diferencias observadas y su alcance,
en lugar de asumir costo cero.

### Distribución del tiempo de CG

Medianas de los porcentajes por corrida, con historial activo:

| Instancia | Construir/actualizar master (%) | Solve master (%) | Preparar pricing (%) | Solve pricing (%) |
|---|---:|---:|---:|---:|
| case1 | 6.71 | 2.81 | 22.69 | 44.08 |
| IB_001 | 5.19 | 2.58 | 33.31 | 38.80 |
| IB_002 | 2.32 | 1.39 | 41.31 | 44.66 |
| IB_003 | 0.81 | 0.52 | 21.62 | 73.58 |

Las medianas de componentes no tienen por qué sumar 100 %. El tiempo de CG
también incluye preparación general y postprocesamiento/bookkeeping.
En esta muestra, el pricing concentra el costo y en IB_003 predomina su solve;
esto orienta el análisis sin demostrar el mismo comportamiento en HARD o en
todo el catálogo.

### Caso limitado y evidencia

case18 excedió 25 s externos en ambos calentamientos. Dos mediciones adicionales
también llegaron al límite antes de detener la secuencia. Las cuatro se
conservan y se excluyen de las comparaciones. El script ahora omite las
mediciones restantes de un caso si su par de calentamiento falla o no coincide.
No se aumentaron los límites ni se sustituyeron esos resultados por otros.

Artifacts locales (Results está ignorado por Git):

- `Results/instrumentation_overhead_20261012_224218_967544.csv`: 36 corridas,
  incluyendo calentamientos y timeouts.
- `Results/instrumentation_overhead_20261012_224218_967544.md`: medianas,
  rangos y limitaciones de la ejecución.

Comando reproducible para las cuatro instancias completas:

```text
python benchmark_instrumentation_overhead.py --cases case1 IB_001 IB_002 IB_003 --repeats 3 --warmup 1 --time 15 --wall-timeout 25
```

Los tiempos parciales tras un corte externo son estimaciones desde el último
checkpoint; pueden incluir su publicación previa al inicio efectivo del
componente. Los tiempos completados usan los límites reales de cada bloque.
La medición anterior tampoco cuantifica el costo de pickle/IPC y de escribir
los archivos adicionales en el runner. Esas diferencias quedan explícitas para
interpretar los porcentajes del tiempo total de las corridas de benchmark.
