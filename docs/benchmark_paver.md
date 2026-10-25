# Benchmark y trazas PAVER

La ejecución devuelve `ExecutionResult`; generación de columnas agrega
`ColumnGenerationMetrics` y `ColumnGenerationDiagnostics`. Los códigos crudos de CPLEX permanecen en
`raw_cplex_status` y nunca se escriben como estados PAVER.

## Estados

`utils/status_normalizer.py` traduce los estados MIP de CPLEX así:

| CPLEX | TerminationStatus | ModelStatus |
|---:|---|---:|
| 101 | Normal | 1 |
| 102 | Normal | 8 |
| 103 | Normal | 10 |
| 104 | OtherLimit | 8/9 según factibilidad |
| 105 | NodeLimit | 8 |
| 106 | NodeLimit | 9 |
| 107 | TimeLimit | 8 |
| 108 | TimeLimit | 9 |
| 109 | Error | 8 |
| 110 | Error | 13 |
| 111 | OtherLimit | 8 |
| 112 | OtherLimit | 9 |
| 113 | Other/UserInterrupt | 8 |
| 114 | Other/UserInterrupt | 9 |
| 115 | Normal | 6 |
| 116 | Error | 8 |
| 117 | Error | 13 |
| 118 | Normal | 18 |
| 119 | Normal | 12 |
| 127 | Other | 8 |
| 131 | TimeLimit | 8 |
| 132 | TimeLimit | 9 |
| 133 | Other | 13 |

Los estados LP también se traducen en el mismo módulo. `ModelStatus=1` indica
optimalidad probada del problema resuelto. En los campos de fase se refiere a
ese LP, pricing o entero restringido; no certifica optimalidad del packing
original. El resultado global de CG conserva `8` para un entero factible.

Para estados LP, el mapeo implementado es: `1 -> Normal/1`, `2 ->
Normal/18`, `3 -> Normal/4`, `4 -> Normal/12`, `5 -> Normal/6`, `6 ->
Other/7 o 6`, `10 -> IterationLimit/7 o 6`, `11 -> TimeLimit/7 o 6`, `12 ->
OtherLimit/7 o 6` y `13 -> UserInterrupt/7 o 6`, donde `7` se usa cuando
existe una solución primal factible y `6` cuando no existe. Estados
desconocidos se clasifican como `Error/13`.

## Trace

El writer produce exactamente estas columnas:

```text
InputFileName,SolverName,Direction,ModelStatus,TerminationStatus,ObjectiveValue,SolverTime,NumberOfIterations
```

`Direction=1` siempre indica maximización. `None` se serializa como `NA`, y
los tiempos se miden con `time.perf_counter()` y se muestran con seis
decimales. El writer valida los estados, rechaza nombres ambiguos como
`Model1` y evita duplicar la combinación PAVER instancia/modelo. El modo
predeterminado es `overwrite`; `append` debe solicitarse explícitamente.
No se escribe `ObjectiveValueEstimate`: el LP de CG no se declara como cota
dual del problema original sin una justificación matemática adicional.

Las métricas CG son: `lp_value` es el último RMP LP resuelto óptimamente y con
objetivo válido; no acredita por sí solo la convergencia de CG.
`restricted_integer_master` es el RMP entero final, `cg_iterations` incluye
la iteración final sin columna mejorante, y `generated_columns` excluye seeds,
duplicados y candidatos rechazados. `cg_time_s` excluye el master entero;
`total_time_s` incluye setup, CG, master entero y overhead.

### Tiempos por fase y diagnóstico CG

El CSV resumido, predeterminado, tiene 24 columnas: conserva las primeras 18
y agrega `master_lp_time_s`, `pricing_time_s`, `cg_stop_reason`,
`lp_convergence_proven`, `interrupted_phase` e `integer_master_model_status`.
El estado del entero permite distinguir un óptimo del pool (`1`) de un
incumbente factible (`8`), independientemente de la comparación con literatura.

Cada corrida genera además dos archivos junto al CSV principal. Para
`Results/benchmark.csv`, son `Results/benchmark_iterations.csv` y
`Results/benchmark_phases.csv`. También se generan en modo `--no-paver`.
Las colisiones y la confirmación de sobrescritura incluyen los tres archivos.

`--detailed-csv` exporta las 44 columnas, con códigos crudos, estados de
segunda fase y reintentos, y evidencia de convergencia. La traza PAVER conserva
sus ocho columnas. El resultado estructurado mantiene siempre todo el detalle.

| Tiempo | Alcance |
|---|---|
| `master_lp_time_s` | Construcción inicial, actualizaciones incrementales, reconstrucciones de respaldo, resoluciones LP y extracción de duales, acumuladas. |
| `pricing_time_s` | Construcción, restricciones adicionales, resoluciones y mapeo de soluciones de todos los pricing; incluye segunda fase y reintentos heurísticos. |
| `integer_master_time_s` | Construcción y resolución del entero final sobre el pool generado. |
| `cg_time_s` | Preparación del hijo, maestro LP, pricing y trabajo restante del ciclo; excluye el entero final y la exportación del layout. |
| `total_time_s` | Tiempo de pared de la llamada completa, incluidos creación del proceso, exportación y cierre. |

Los tiempos no se redondean internamente; el CSV muestra seis decimales.
En un corte externo, el padre extiende el último snapshot hasta el momento
de corte y atribuye ese intervalo a la fase activa según el último snapshot
recibido. El tiempo de cierre del
proceso solo incrementa el total. Si el hijo sale inesperadamente, se
conservan los tiempos del último snapshot recibido, sin inventar el instante
de salida. `snapshot_time_s` y `active_phase` son datos internos de seguimiento.

`cg_stop_reason` identifica el motivo de cierre de generación:

| Motivo | Significado |
|---|---|
| `pricing_converged` | Hay evidencia suficiente del pricing principal para cerrar el LP del universo de columnas considerado. |
| `pricing_nonpositive_unproven` | El valor devuelto no es positivo, pero falta una prueba suficiente. |
| `duplicate` | Se devuelve una columna duplicada y no se incorpora una alternativa. |
| `stagnation` | Actúa el criterio heurístico de estancamiento. |
| `lp_failure` / `lp_limit` | Falta un LP con objetivo y duales utilizables, por fallo o límite. |
| `pricing_no_solution` / `pricing_limit` | El pricing no devuelve una solución utilizable o se corta por límite sin demostrar cierre. |
| `pricing_no_column` | Hay objetivo positivo pero falta una columna utilizable. |
| `wall_clock_timeout` / `user_interrupt` / `child_exit` / `error` | La generación se interrumpe antes de registrar otro motivo de cierre. |

Un timeout posterior en el entero o la exportación conserva el motivo por el
que terminó CG. `interrupted_phase` identifica la última fase con límite o
error: `setup`, `preparation`, `master_lp`, `pricing`, `cg_overhead`,
`integer_master` o `layout_export`. `runner` indica una excepción capturada
por el runner sin un resultado estructurado del solver.

`lp_convergence_proven` se escribe como `True` o `False`; `False` significa
que no se registró una prueba, no que se haya demostrado falta de convergencia.
Requiere un LP válido y óptimo, y pricing principal con los duales originales.
En modo detallado, `convergence_basis` es `optimal_pricing` cuando el pricing fue probado óptimo
con objetivo <= `EPS`, o `pricing_upper_bound` cuando una cota superior finita
es <= `EPS`. La cota puede acreditar cierre aunque el solver haya terminado
por límite; ese límite sigue registrado en el estado global. Se rechazan
cotas no disponibles, infinitas, sentinelas de CPLEX y estados numéricamente
inválidos. La segunda fase y los pricing con exclusiones no aportan esta
prueba. `pricing_objective` y `pricing_best_bound` conservan la evidencia del
último pricing principal; no son cotas del packing original.

En modo detallado, cada prefijo `lp`, `pricing`, `pricing_phase2`, `auxiliary_pricing`,
`auxiliary_pricing_phase2` e `integer_master` tiene tres columnas:
`*_model_status`, `*_termination_status` y `*_raw_cplex_status`. Describen
la última resolución completada y reportada de cada tipo. Los reintentos y
la segunda fase no sobrescriben el pricing principal. Una fase nunca
reportada se escribe como `NA`; si el padre interrumpe una resolución en
curso, sus códigos anteriores siguen refiriéndose a la última resolución
reportada y `interrupted_phase` informa el corte actual.

### Registro por iteración

`*_iterations.csv` contiene una fila por intento del ciclo maestro LP/pricing,
con numeración propia desde 1. Incluye intentos fallidos o interrumpidos;
por eso la cantidad de filas puede superar `cg_iterations`, que conserva su
definición histórica. La construcción inicial del maestro corresponde a la
primera fila. Las posiciones y columnas iniciales se preparan antes de esa fila.

| Campo del registro | Significado |
|---|---|
| `master_build_time_s` | Construcción inicial, actualización incremental, reconstrucción de respaldo y preparación del tipo de problema LP. |
| `master_solve_time_s` | Tiempo de las llamadas a `model.solve()` del maestro LP; excluye extracción de duales, estados y solución. |
| `pricing_build_time_s` | Primera construcción y actualizaciones del objetivo del pricing reutilizado; en modo reconstrucción, armado de cada modelo. Con mejoras opcionales, incluye restricciones de exclusión y preparación del objetivo/restricción de su segunda fase. |
| `pricing_solve_time_s` | Tiempo de todas las llamadas a `model.solve()` del pricing en ese intento, incluidas segunda fase y alternativas. |
| `master_lp_time_s` / `pricing_time_s` | Totales de fase: incluyen los componentes anteriores y postprocesamiento/bookkeeping; no son solo solve. |
| `iteration_time_s` | Tiempo de pared del intento, incluido el trabajo entre fases. Excluye el entero final. |
| `pool_before` / `pool_after` | Tamaño total del pool al comienzo y al final; incluye las columnas iniciales. |
| `generated_columns` | Columnas aceptadas durante ese intento, excluyendo seeds y duplicados. |
| `lp_value`, `pricing_objective`, `pricing_best_bound` | Valores reportados en ese intento; un LP/pricing que no se ejecutó no hereda valores de la fila anterior. |
| `pricing_calls` / `pricing_phase2_calls` | Intentos de solve de primera fase (principal y auxiliares) y de segunda fase, respectivamente. |
| `completed` | `True` si hubo un par LP/pricing utilizable y el intento cerró sin error ni corte externo. No acredita convergencia ni optimalidad. |
| `stop_reason` | `column_added`, `alternative_column_added`, motivo de cierre CG o interrupción/error de esa fila. |

Los estados LP, pricing principal, segunda fase y auxiliares se registran
independientemente para cada intento. Si falla la segunda fase antes de
reportar un estado CPLEX, se informa `Error/13` con código crudo `NA`; si falla
el postprocesamiento después de reportarlo, se conserva ese estado y la fila
queda incompleta/con error. Los contadores de llamadas incluyen solves que
terminan con excepción; una preparación fallida antes del solve no suma una
llamada.

Un solve que devuelve un incumbente al alcanzar un límite puede producir una
fila `completed=True`: el intento del ciclo terminó con datos utilizables,
pero sus estados siguen indicando el límite. Un corte externo durante la
fila produce `completed=False`.

Al interrumpir el hijo, el padre conserva las filas cerradas y finaliza una
fila parcial con `completed=False`. Los tiempos parciales de fase y componente
se estiman desde el último checkpoint recibido: pueden incluir el intervalo
de publicación previo al comienzo efectivo del componente. Los tiempos de
componentes completados excluyen la publicación del checkpoint. El costo de
cerrar el proceso no se atribuye a la fila ni a las fases.

El transporte envía cada fila cerrada una vez y solo la fila activa en los
snapshots. No reenvía el historial entero por cada actualización. La API CG
permite `record_iterations=False` para comparar el costo adicional del historial;
el runner registra las iteraciones por defecto y mantiene siempre los tiempos.

### Totales y porcentajes por instancia

`*_phases.csv` contiene una fila por instancia, con los seis acumulados
`master_lp`, `pricing`, `master_build`, `master_solve`, `pricing_build` y
`pricing_solve`, además de los denominadores `total_time_s` y `cg_time_s`.
Para cada acumulado exporta:

- `*_percent_total = 100 * componente / total_time_s`.
- `*_percent_cg = 100 * componente / cg_time_s`.

Un denominador no positivo se escribe como `NA`. Los agregados maestro/pricing
contienen sus componentes: sus porcentajes no deben sumarse con los de build
y solve. El resto de CG corresponde a preparación general y bookkeeping.
`iteration_records` indica filas registradas, distinto del contador histórico
`cg_iterations` cuando existe un intento parcial o fallido.

La validación del costo del registro y sus límites de interpretación se
documenta en [instrumentation_validation.md](instrumentation_validation.md).

## Ejecución

Corrida normal:

```text
python main.py --case case1 --time 60 --output check_case1.trc
```

El archivo se genera bajo `Results/`. Para agregar explícitamente a una
traza compatible se puede usar `--append`; las combinaciones duplicadas se
rechazan.

La ejecución normal genera la traza y ejecuta PAVER después:

```text
python main.py --all --time 1200 --output comparison.trc
```

Para generar solamente el `.trc`, sin ejecutar PAVER, se puede usar
`--no-paver`:

```text
python main.py --all --time 1200 --output comparison.trc --no-paver
```

La ruta de instalación de PAVER se lee desde `paver.properties`, mediante la
propiedad `paver.path`. Puede reemplazarse para una ejecución puntual con:

```text
python main.py --all --time 1200 --paver-path "D:\Paver" --paver-output "Results\comparison_paver"
```

La invocación usa `py -3.6`, `--ignoredualbounds`, `--mintime 0.001` y un
`--failtime` igual al `--time` de la corrida. Se ignoran las cotas duales
porque la comparativa incluye modelos con espacios de solución diferentes,
como los modelos con y sin rotación. Si PAVER no existe, no puede ejecutarse
o termina con error, el programa informa el problema y conserva la traza
generada.

Benchmark:

```text
python benchmark_runner.py --input "benchmark_validation_baseline.csv" --output Results/benchmark.csv --trace Results/benchmark.trc --time 1200
```

Para obtener el CSV completo de diagnóstico, agregar `--detailed-csv`:

```text
python benchmark_runner.py --input "benchmark_validation_baseline.csv" --output Results/benchmark_detallado.csv --time 1200 --detailed-csv --no-paver
```

El runner ejecuta todas las filas que existan en el CSV, ejecuta solamente CG
con las heurísticas de finalización desactivadas, preserva el orden de entrada
y continúa si una instancia falla. `--expected-count` es opcional y solo
verifica una cantidad esperada cuando se proporciona. El CSV se construye
directamente desde el resultado
estructurado, no desde el `.trc`. Incluye `error_message` como columna
diagnóstica adicional. Una ausencia de objetivo se escribe como `NA`. Después
de cerrar el CSV y la traza, el mismo comando ejecuta PAVER leyendo
`paver.path` desde `paver.properties`; el informe queda en
`Results/benchmark_paver/index.html`. Para omitir este paso se puede agregar
`--no-paver`. Si no se indica `--trace`, el runner crea automáticamente una
traza junto al CSV para poder ejecutar PAVER.

El gap firmado para maximización es:

```text
100 * (optimal_literature - restricted_integer_master) / optimal_literature
```

Los estados experimentales son `OPTIMAL`, `SUBOPTIMAL`,
`REFERENCE_EXCEEDED`, `LP_FAIL`, `LP_OK_IP_FAIL`, `TIMEOUT_FEASIBLE`,
`TIMEOUT_NO_SOLUTION` y `ERROR`. `OPTIMAL` solo significa coincidencia con
la referencia de literatura, no una certificación PAVER.

## Interpretar LP e IP restringidos

El maestro LP se actualiza incrementalmente y se reconstruye si falla una
actualización. El maestro entero final se construye desde el pool disponible
al terminar CG. No genera columnas nuevas durante el árbol entero.

`lp_value` corresponde al último pool resuelto como LP. Las columnas añadidas
en una exploración opcional o justo antes de un corte pueden llegar al maestro
entero sin otra resolución LP. Para diagnosticar una brecha sobre el mismo
pool, comprobar también esa correspondencia. El runner de benchmarks fuerza
`finalization_heuristics=False`, por lo que no ejecuta la exploración opcional.

| Observación | Interpretación |
|---|---|
| LP coincide con la referencia e IP es `NA` | No se dispone de un entero; revisar terminación, fase alcanzada y `error_message`. |
| LP coincide con la referencia y el incumbente IP es inferior | Hay una diferencia numérica; falta comprobar si el IP restringido se resolvió óptimamente. |
| IP restringido probado óptimo e inferior a la referencia, con columnas válidas | El pool no expresa una solución entera de ese valor; revisar además la cobertura del espacio de soluciones y la formulación. |
| IP coincide con una referencia válida y la geometría es factible | Coincide con el óptimo de referencia; el método general sigue sin garantizarlo para todas las instancias. |

`LP_OK_IP_FAIL` significa que existe un valor LP pero no un objetivo entero;
no significa «LP igual al óptimo de literatura e IP inferior». `SUBOPTIMAL`
compara el incumbente con la referencia bajo terminación normal, pero no
certifica que ese incumbente sea el óptimo del IP restringido. El gap queda
`NA` cuando falta el objetivo entero; no debe completarse con cero ni con
una estimación. El estado global de CG conserva también límites y errores
anteriores, aunque el maestro entero final tenga una solución.

Para declarar insuficiencia del pool, conservar la evidencia de optimalidad
del maestro entero restringido y revisar la factibilidad de sus columnas.
Para declarar convergencia LP, se requiere una prueba suficiente del pricing:
un incumbente no positivo tras un límite sin cota suficiente, un duplicado o un corte heurístico
no constituyen esa prueba.

### Evidencia disponible al 8 de octubre de 2026

Se revisaron `Results/benchmark.csv`, `benchmark_20260923.csv`,
`benchmark_case_fix.csv`, `benchmark_test.csv`, `master_rebuild_before.csv` y
`master_rebuild_after.csv`. No se encontró una fila con objetivos LP e IP
numéricos que acreditara LP igual a la referencia e IP inferior. Hay filas
con IP `NA` por timeout o interrupción. Por ejemplo, `IB_009` en
`benchmark_test.csv` tiene LP `45`, referencia `45` e IP `NA`.

Estos archivos están bajo `Results/`, ignorado por Git; su presencia y
contenido corresponden a la revisión local fechada, no a fixtures permanentes.
`benchmark_validation_baseline.csv` es un catálogo de entrada con campos de
resultados vacíos, no una corrida que confirme una brecha.

El caso `50 x 20 / 13 x 8` sí reprodujo LP aproximadamente `7` e IP restringido
óptimo `6` mediante la ruta de reconstrucción, mientras el flujo incremental
actual obtuvo `7/7`. La metodología y su alcance se detallan en
[algorithm.md](algorithm.md#verificación-del-8-de-octubre-de-2026).

Para nuevas comparaciones, registrar versión del código, dimensiones, flags,
presupuesto temporal y terminación de cada fase. Reservar tiempo para el IP
es una decisión del protocolo experimental: el runner actual comparte el
límite de pared por instancia y puede agotarlo durante CG antes de resolver
el maestro entero.

## Validación PAVER

El repositorio contiene un fixture en `tests/fixtures/paver_smoke.txt`.
Si PAVER está instalado localmente, cargar ese fixture con el lector oficial
y confirmar que `Direction=1`, `Normal`, `NodeLimit` y `TimeLimit` se aceptan.
La validación no es una dependencia de los tests del proyecto.
