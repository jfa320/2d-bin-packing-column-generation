# Benchmark y trazas PAVER

La ejecución devuelve `ExecutionResult`; generación de columnas agrega
`ColumnGenerationMetrics`. Los códigos crudos de CPLEX permanecen en
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

Los estados LP también se traducen en el mismo módulo. `ModelStatus=1` se
usa solo para una optimalidad global probada por el algoritmo. Una solución
entera factible sin esa prueba usa `8`.

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
un incumbente no positivo tras un límite, un duplicado o un corte heurístico
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
