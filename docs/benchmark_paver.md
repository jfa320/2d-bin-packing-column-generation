# Experimentación, métricas y PAVER

Ejecutar desde la raíz del repositorio, con el entorno Python/CPLEX del
solver. Para comparar todos los modelos de `main.py`, consultar el
[README](../README.md#ejecución-de-instancias). `benchmark_runner.py` ejecuta
solo el modelo propio de generación de columnas, con
`finalization_heuristics=False`.

## Ejecución

```powershell
python benchmark_runner.py --input benchmark_validation_baseline.csv --output Results/benchmark.csv --trace Results/benchmark.trc --time 1200
```

La entrada contiene `instance,family,L,W,l,w,optimal_literature,source`.
El runner procesa todas sus filas en orden y continúa si una instancia falla.
`--expected-count 30` permite comprobar opcionalmente la cantidad de filas.
Indicar `--input` explícitamente evita depender del nombre predeterminado.

`--time` es el presupuesto de pared por instancia compartido por CG y el
maestro entero; CG puede consumirlo antes de que se obtenga un entero. Los
límites cooperativos del solver y el cierre del proceso pueden añadir
sobrepasos. Para verificaciones con solver, usar también un límite externo.

El CLI ejecuta PAVER al terminar. Usar `--no-paver` para omitirlo y
`--detailed-csv` para exportar todas las columnas de diagnóstico:

```powershell
python benchmark_runner.py --input benchmark_validation_baseline.csv --output Results/benchmark_detallado.csv --time 1200 --detailed-csv --no-paver
```

Para `Results/benchmark.csv`, las salidas son:

| Archivo | Contenido |
|---|---|
| `benchmark.csv` | Resumen por instancia: 24 columnas, o 44 con `--detailed-csv`. |
| `benchmark_iterations.csv` | Una fila por intento del ciclo LP/pricing. |
| `benchmark_phases.csv` | Acumulados y porcentajes de tiempo por instancia. |
| `benchmark.trc` | Traza PAVER, si se solicita o si PAVER está habilitado. |

Los tres CSV se escriben incrementalmente después de cada instancia. Los
sidecars también se generan con `--no-paver`. Elegir nombres nuevos: el CLI
pide confirmación si existen salidas; la API rechaza sobrescribir salvo
`overwrite=True`. `Results/` está ignorado por Git.

## Generación múltiple

El benchmark usa una columna por iteración por defecto (`--pool-mode off`),
independientemente de `USE_PRICING_SOLUTION_POOL` en `config.py`. Para incorporar
hasta cinco columnas del pool habitual del pricing:

```powershell
python benchmark_runner.py --input benchmark_validation_baseline.csv --output Results/pool_passive.csv --time 60 --pool-mode passive --pool-columns 5 --pool-capacity 20 --seed 1 --threads 1 --no-paver
```

`--pool-mode populate` permite una búsqueda adicional, acotada por
`--populate-time`, `--populate-ratio` y el presupuesto restante. Las opciones
`--populate-limit` y `--pool-intensity` controlan la generación y la intensidad
de búsqueda. `--pool-columns 1` conserva el comportamiento de una columna.
La validación y selección de candidatos se describen en
[algorithm.md](algorithm.md#varias-columnas-del-solution-pool).

Los modos `passive` y `populate` agregan `<nombre>_pool.jsonl`, sin cambiar los
esquemas CSV. Contiene configuración, semilla, hilos, versiones, hashes de
fuentes y resultados completos, incluidas las métricas del pool. Este archivo
también está protegido contra sobrescritura. Para comparar variantes, usar
las mismas instancias, presupuestos, semillas e hilos y salidas distintas.

El diagnóstico independiente observa una trayectoria de una columna y
reproduce sus duales sin incorporar candidatos adicionales al maestro:

```powershell
python pricing_pool_preflight.py --cases case1 IB_004 case18 --repeats 3 --time 60 --replay-time 30 --wall-timeout 100
```

Guarda controles, snapshots y reportes en un directorio nuevo de `Results/`.
Los replays tienen un presupuesto separado y no miden una aceleración de la
generación múltiple. `--seeds` permite seleccionar las semillas.

## Objetivos y estados

Los objetivos ausentes se escriben como `NA`, los tiempos con seis decimales
y los booleanos como `True`/`False`. No se redondea antes de calcular métricas.

| Campo | Interpretación |
|---|---|
| `lp_value` | Último RMP LP resuelto óptimamente con objetivo válido; no acredita por sí solo convergencia del universo completo. |
| `restricted_integer_master` | Objetivo entero disponible sobre el pool generado. |
| `integer_master_model_status` | `1`: óptimo del pool; `8`: incumbente factible. `NA`: sin estado reportado. |
| `cg_iterations` | Contador CG, incluida la iteración final sin columna mejorante. |
| `generated_columns` | Columnas incorporadas; excluye seeds, duplicados y candidatos rechazados. |
| `lp_convergence_proven` | Se registró una prueba suficiente de cierre del LP. `False` indica ausencia de prueba. |
| `interrupted_phase` | Última fase con límite o error; puede corresponder al entero o a la exportación, después de CG. |

El estado experimental compara el entero con `optimal_literature`: `OPTIMAL`
significa coincidencia con esa referencia, `SUBOPTIMAL` un valor inferior bajo
terminación normal y `REFERENCE_EXCEEDED` uno superior. No certifican por sí
solos optimalidad global. `LP_FAIL` y `LP_OK_IP_FAIL` distinguen la ausencia
de objetivo LP o entero; `TIMEOUT_FEASIBLE`, `TIMEOUT_NO_SOLUTION` y `ERROR`
informan límites y fallos. Un IP `NA` no demuestra una brecha LP/IP.

El gap firmado de maximización es:

```text
100 * (optimal_literature - restricted_integer_master) / optimal_literature
```

Sin objetivo entero, el gap queda `NA`. Para atribuir una diferencia a
insuficiencia del pool, comprobar optimalidad del entero restringido,
factibilidad geométrica y correspondencia entre los pools LP/IP.

## Cierre de CG y diagnóstico

| `cg_stop_reason` | Significado |
|---|---|
| `pricing_converged` | Pricing principal con evidencia suficiente de cierre. |
| `pricing_nonpositive_unproven` | Incumbente no positivo sin prueba suficiente. |
| `duplicate` | Parada por columna duplicada. |
| `lp_failure` / `lp_limit` | LP sin objetivo y duales utilizables, por fallo o límite. |
| `pricing_no_solution` / `pricing_limit` | Pricing sin solución utilizable o limitado sin demostrar cierre. |
| `pricing_no_column` | Objetivo positivo sin columna utilizable. |
| `wall_clock_timeout` / `user_interrupt` / `child_exit` / `error` | Interrupción antes de registrar otro cierre. |

La prueba de cierre requiere un LP óptimo y pricing principal con sus duales
originales: objetivo óptimo o cota superior finita menor o igual a `EPS`.
`convergence_basis` distingue `optimal_pricing` y `pricing_upper_bound`.
Una cota suficiente puede probar cierre aun con terminación por límite;
ese límite sigue registrado. La segunda fase y los pricing con exclusiones
no aportan ese certificado. `pricing_objective` y `pricing_best_bound` son
evidencia del pricing, no cotas del packing original.

En modo detallado, los prefijos `lp`, `pricing`, `pricing_phase2`,
`auxiliary_pricing`, `auxiliary_pricing_phase2` e `integer_master` tienen
`*_model_status`, `*_termination_status` y `*_raw_cplex_status`. Cada grupo
describe la última resolución reportada de ese tipo, sin sobrescribir otros
grupos. Una fase nunca reportada queda `NA`; `interrupted_phase` identifica
el corte actual aunque permanezcan estados de una resolución anterior.

## Tiempos por fase y por iteración

| Tiempo | Alcance |
|---|---|
| `master_lp_time_s` | Construcción, actualizaciones/rebuild, solves LP, extracción de resultados y duales. |
| `pricing_time_s` | Preparación, solves y postprocesamiento de todos los pricing, incluidas alternativas y segunda fase. |
| `integer_master_time_s` | Construcción y resolución del entero final. |
| `cg_time_s` | Preparación y ciclo CG; excluye entero final y exportación del layout. |
| `total_time_s` | Llamada completa, incluidos creación del proceso, exportación y cierre. |

En `*_iterations.csv`, `master_build_time_s` incluye construcción,
actualización y preparación del LP. `pricing_build_time_s` incluye la primera
construcción y las actualizaciones de objetivo del modelo reutilizado; en
modo reconstrucción incluye cada armado. `master_solve_time_s` y
`pricing_solve_time_s` miden solo llamadas a `model.solve()`, sin extracción
de duales ni postprocesamiento. Los totales de fase contienen esos componentes;
no deben sumarse otra vez con ellos.

El registro incluye intentos fallidos e interrumpidos, numerados desde 1.
La construcción inicial del maestro corresponde a la primera fila; posiciones
y seeds se preparan antes. `pool_before`/`pool_after` incluyen seeds y
`generated_columns` cuenta solo incorporaciones del intento. Los objetivos y
estados de una fase no ejecutada no heredan los de la fila anterior.

`completed=True` indica que el intento cerró con datos utilizables; no prueba
convergencia ni optimalidad, y puede coexistir con un límite nativo. Las
llamadas se cuentan al intentar el solve, incluso si lanza una excepción;
una preparación fallida antes del solve no suma una llamada.

Tras un corte externo se conservan las filas cerradas y se finaliza la activa
con `completed=False`. Los tiempos parciales se estiman desde el último
checkpoint y pueden incluir su publicación. El cierre del proceso incrementa
solo el tiempo total. Si el hijo sale inesperadamente, se conserva el último
snapshot sin inventar su instante de salida. `record_iterations=False` permite
omitir el historial en la API; el runner lo registra por defecto.

`*_phases.csv` acumula `master_lp`, `pricing`, `master_build`, `master_solve`,
`pricing_build` y `pricing_solve`, y calcula para cada uno:

```text
percent_total = 100 * componente / total_time_s
percent_cg = 100 * componente / cg_time_s
```

Un denominador no positivo produce `NA`. `iteration_records` cuenta filas,
que pueden superar `cg_iterations` si hubo intentos parciales o fallidos.
Las mediciones incluyen el costo de la instrumentación; no debe asumirse
costo cero al comparar ejecuciones con distinto protocolo de registro.

## Traza PAVER

El writer produce ocho columnas:

```text
InputFileName,SolverName,Direction,ModelStatus,TerminationStatus,ObjectiveValue,SolverTime,NumberOfIterations
```

`Direction=1` indica maximización. `None` se serializa como `NA`. El writer
valida los estados y evita repetir pares instancia/modelo. Sobrescribe por
defecto; `main.py --append` agrega explícitamente pares nuevos compatibles.
No se escribe `ObjectiveValueEstimate`: el LP de CG no se declara cota dual
del packing original.

Los estados crudos de CPLEX se conservan en el diagnóstico y se traducen en
[status_normalizer.py](../utils/status_normalizer.py). `ModelStatus=1`
acredita optimalidad del modelo resuelto, que puede ser un LP o un entero
restringido. CG conserva `8` como estado global de un entero factible.
`TerminationStatus` informa `Normal`, `TimeLimit`, `NodeLimit`,
`IterationLimit`, otros límites, interrupciones o errores.

## Configuración de PAVER

La instalación externa debe contener `src/paver/paver.py`. Configurar su
directorio raíz en [paver.properties](../paver.properties), adaptando la ruta
a la máquina:

```properties
paver.path=D:\Paver
```

La integración de [paver_runner.py](../utils/paver_runner.py) usa `py -3.6`,
con las dependencias de PAVER. El solver usa Python 3.10 y CPLEX en su propio
entorno. Para comprobar PAVER desde PowerShell:

```powershell
$paverRoot = 'D:\Paver'
py -3.6 "$paverRoot\src\paver\paver.py" --help
```

`main.py` y `benchmark_runner.py` generan el informe al finalizar, salvo que
se pase `--no-paver`. `--paver-path` permite reemplazar la ruta configurada y
`--paver-output` elegir el directorio del informe. Si PAVER falla, se conservan
los resultados y la traza. Por ejemplo:

```powershell
python main.py --cases case2 case4 --time 1200 --output comparison.trc --paver-path "D:\Paver" --paver-output "Results/comparison_paver"
```

Para regenerar el HTML de una traza existente, desde la raíz del repositorio:

```powershell
$paverRoot = 'D:\Paver'
$tracePath = (Resolve-Path -LiteralPath 'Results/comparison.trc').Path
$reportPath = Join-Path (Get-Location).Path 'Results/comparison_paver'
Push-Location -LiteralPath $paverRoot
try {
    py -3.6 src/paver/paver.py $tracePath --ignoredualbounds --mintime 0.001 --failtime 1200 --writehtml $reportPath
} finally {
    Pop-Location
}
```

`--failtime` debe coincidir con el límite del experimento. `--mintime 0.001`
evita problemas estadísticos con tiempos muy pequeños sin modificar la traza.
`--ignoredualbounds` evita comparar cotas de modelos con espacios de soluciones
distintos. La integración automática aplica esas opciones y toma `failtime`
del argumento `--time`.

## Lectura del informe de PAVER

| Página | Contenido |
|---|---|
| `index.html` | Resumen y acceso al informe. |
| `stat_Status.html` | Terminaciones normales, límites y errores. |
| `solvedata.html` | Objetivo, tiempo y estado por instancia/modelo. |
| `stat_SolutionQuality.html` | Cantidad de ítems obtenida. |
| `stat_Efficiency.html` y perfiles | Tiempos y proporción de instancias resueltas. |

`virt.best` toma el mejor resultado por instancia; es una referencia virtual.
Comparar corridas con las mismas instancias y presupuesto: las medias y los
perfiles dependen de los casos y del tratamiento de límites.

PAVER informa optimalidad del modelo resuelto. Un maestro entero óptimo sobre
un pool restringido no certifica el óptimo global del packing. Para interpretar
los resultados, revisar objetivo, factibilidad y referencia.

El fixture [paver_smoke.txt](../tests/fixtures/paver_smoke.txt) permite comprobar
el lector de trazas sin resolver nuevos modelos de optimización.
