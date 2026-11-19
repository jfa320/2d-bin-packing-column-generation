# Experimentación, métricas y PAVER

Ejecutar desde la raíz del repositorio, con el entorno Python/CPLEX del
solver. Para comparar todos los modelos de `main.py`, consultar el
[README](../README.md#ejecución-de-instancias). `benchmark_runner.py` ejecuta
solo el modelo propio de generación de columnas. Las heurísticas de finalización
están desactivadas por defecto y se controlan mediante tres flags independientes
sobre el mismo pricing persistente. El solution pool está activo.

Para interpretar un informe ya generado, consultar los
[archivos de salida](#archivos-que-entrega-paver), la
[lectura de tablas](#qué-leer-en-las-tablas) y la
[lectura de gráficos](#qué-información-sacar-de-los-gráficos).

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
| `benchmark_pool.jsonl` | Configuración del pool y las heurísticas, versiones, hashes y resultados completos. |
| `benchmark.trc` | Traza PAVER, si se solicita o si PAVER está habilitado. |

Los tres CSV se escriben incrementalmente después de cada instancia. Los
sidecars también se generan con `--no-paver`. Elegir nombres nuevos: el CLI
pide confirmación si existen salidas; la API rechaza sobrescribir salvo
`overwrite=True`. `Results/` está ignorado por Git.

## Inicialización

La estrategia predeterminada es `homogeneous`, con filas de una sola orientación.
La alternativa experimental `--initialization mixed` conserva esas filas y agrega
filas con ambas orientaciones mediante una búsqueda geométrica acotada:

```powershell
python benchmark_runner.py --input benchmark_validation_baseline.csv --output Results/initial_mixed.csv --time 60 --initialization mixed --initial-mixed-max-columns 24 --seed 1 --threads 1 --no-paver
```

El límite afecta solo a columnas mixtas adicionales; cero mantiene el pool
homogéneo. Se consideran hasta cuatro alturas, tres composiciones y dos órdenes
por composición, como describe el [algoritmo](algorithm.md#rebanadas-e-inicialización).
No se requiere una resolución adicional del pricing para generar las semillas.
La API `run_benchmark` admite `initialization` e `initial_mixed_max_columns`;
omitirlos sigue `config.py`. El ejecutor transmite los valores resueltos al hijo.

El JSONL del pool guarda ambos parámetros, los hashes del generador y sus
dependencias, y las métricas `initialization_time_s`, `initial_columns`,
`initial_mixed_columns` e `initial_lp_value`. El primer LP tiene su estado en
`result.diagnostics.initial_lp_status`; un objetivo ausente permanece ausente,
y un valor sin estado óptimo no debe tratarse como óptimo del pool. Los esquemas
CSV se conservan. Con `--pool-mode off` no se genera ese JSONL; las métricas
siguen disponibles en los resultados estructurados de la API.

La inicialización consume el presupuesto global y su tiempo está incluido en
`cg_time_s`. `generated_columns` excluye todas las semillas, también las mixtas.
No se calcula un entero inicial adicional durante la ejecución normal.
Para comparar estrategias, conservar greedy, pool, los tres flags de heurísticas,
estabilización dual, semilla, hilos y presupuesto, cambiando solo la inicialización.
Un mejor primer LP no demuestra por sí solo una mejora de tiempo o de calidad final.

## Generación múltiple

El benchmark usa el pool habitual por defecto (`--pool-mode passive`), con hasta
cinco columnas por iteración. `--pool-mode off` selecciona un control explícito
de una columna, independientemente de `USE_PRICING_SOLUTION_POOL` en `config.py`.
Para fijar explícitamente la configuración del pool:

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

Para comparar heurísticas, mantener el pool activo y variar solamente los flags
`--pricing-second-phase`, `--pricing-final-enrichment` y
`--pricing-duplicate-retries`, conservando los demás parámetros. Pueden combinarse
libremente; las formas `--no-pricing-*` las desactivan explícitamente. Si se omiten,
siguen los tres flags de `config.py`, todos en `False` por defecto. El enriquecimiento
solo ejecuta la segunda fase cuando esta también está habilitada.

Todos los flujos usan una única instancia CPLEX del pricing; la estabilización
dual está desactivada por defecto y no depende de estos flags. En la API,
`run_benchmark` acepta `use_pricing_second_phase`, `use_pricing_final_enrichment`
y `use_pricing_duplicate_retries`; omitir `pool_options` usa el pool habitual y
pasar `pool_options=None` solicita el control de una columna. El JSONL registra
los tres valores resueltos y `pricing_mode="reuse"`, además de las opciones del pool.

La [guía del algoritmo](algorithm.md#heurísticas-de-finalización) detalla los
tres mecanismos y su configuración independiente.

El diagnóstico independiente observa una trayectoria de una columna y
reproduce sus duales sin incorporar candidatos adicionales al maestro:

```powershell
python pricing_pool_preflight.py --cases case1 IB_004 case18 --repeats 3 --time 60 --replay-time 30 --wall-timeout 100
```

Guarda controles, snapshots y reportes en un directorio nuevo de `Results/`.
Los replays tienen un presupuesto separado y no miden una aceleración de la
generación múltiple. `--seeds` permite seleccionar las semillas.

## Comparación LP y entera

Con `--compare-models`, el benchmark ejecuta CG, Pisinger–Sigurd con rotación
y Andrade–Birgin sobre las mismas instancias. Usá un CSV con el formato de
entrada del benchmark. Este modo admite `0` o `NA` en `optimal_literature`;
en ambos casos el gap porcentual de CG queda como `NA`.

```powershell
python benchmark_runner.py --compare-models --input benchmark_validation_baseline.csv --output Results/rotados.csv --time 60 --seed 2 --threads 1 --no-paver
```

- `rotados_lp.csv` pone las cotas certificadas en `value`. El último maestro
  restringido de CG queda en `rmp_value`, y el objetivo primal de un
  comparador con LP inconcluso, en `lp_primal_value`. El tiempo de un LP de CG
  certificado se mide hasta recibir la prueba del pricing o determinar el
  dominio vacío. Un timeout posterior del maestro entero conserva esa prueba.
- `rotados_integer.csv` informa el valor factible y su garantía en
  `value_kind`: `optimal`, `incumbent`, `restricted_integer` o
  `unavailable`. Para CG, `integer_master_time_s` mide su fase entera y
  `time_s` la ejecución completa.

Cada fila registra el límite, la semilla y los hilos solicitados. Si se
omiten semilla o hilos, se usan los valores predeterminados de CPLEX.
Cada comparador tiene una corrida LP y una MIP con el límite indicado.
CG comparte su límite entre la generación de columnas y el maestro entero.
`termination_status` describe el resultado de la fase, mientras que
`run_termination_status` describe la corrida completa.
Las trazas y PAVER siguen reportando los resultados habituales de CG.

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
construcción y las actualizaciones de objetivo del modelo reutilizado. Incluye
además la preparación y restauración de los cambios temporales
de las búsquedas auxiliares. `master_solve_time_s` y
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

La traza `.trc` es la **entrada de PAVER**, generada por este proyecto.
Es texto separado por comas, con una definición de registro en líneas que
empiezan con `*`. Cada fila de datos representa un par instancia/modelo.
El writer produce ocho columnas:

```text
InputFileName,SolverName,Direction,ModelStatus,TerminationStatus,ObjectiveValue,SolverTime,NumberOfIterations
```

| Columna | Contenido en este proyecto |
|---|---|
| `InputFileName` | Nombre de la instancia. |
| `SolverName` | Identificador del modelo o algoritmo. |
| `Direction` | `1` para maximizar la cantidad de rectángulos. |
| `ModelStatus` | Estado del modelo: por ejemplo, `1` óptimo, `8` factible, `9` sin solución. |
| `TerminationStatus` | Motivo de terminación: `Normal`, `TimeLimit`, `NodeLimit`, `Error`, etc. |
| `ObjectiveValue` | Cantidad de rectángulos del resultado reportado; `NA` si falta. |
| `SolverTime` | Tiempo reportado por el ejecutor, en segundos. |
| `NumberOfIterations` | Iteraciones reportadas; en CG, iteraciones del algoritmo. `NA` si no se informan. |

Ejemplo ilustrativo de una ejecución factible de CG:

```text
* Trace Record Definition
* InputFileName,SolverName,Direction,ModelStatus,TerminationStatus,ObjectiveValue,SolverTime,NumberOfIterations
case1,Model5Orchestrator,1,8,Normal,4,1.250000,6
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

## Archivos que entrega PAVER

Con `--writehtml`, PAVER crea una carpeta de informe. En la integración del
proyecto, una traza `Results/comparison.trc` produce por defecto
`Results/comparison_paver/`. Abrir `index.html` en el navegador y conservar
**la carpeta completa** para que funcionen los enlaces y las imágenes.
Los archivos dependen de los atributos disponibles, los filtros y las opciones;
no todas las corridas generan todas las familias siguientes.

```text
comparison.trc                         # entrada, escrita por el proyecto
comparison_paver/                      # salida de PAVER
    index.html
    documentation.html
    solvedata.html
    raw.html
    stat_Status.html
    stat_SolutionQuality.html
    stat_Efficiency.html
    stat_Statusdata000.html
    stat_Statuscount000.png
    stat_Efficiencydata000.html
    stat_Efficiencyratio000_virt.best.html
    stat_Efficiencyarithmean000.png
    stat_Efficiencygeommean000.png
    stat_Efficiencysh.geommean000.png
    stat_Efficiencyboxplot000.png
    stat_Efficiencyboxplot000_virt.best.png
    stat_Efficiencyclose000_virt.best.png
    stat_Efficiencybetter000_virt.best.png
    stat_Efficiencyworse000_virt.best.png
    stat_Efficiencyprofilerel003.png
    stat_Efficiencyprofileabs003.png
```

Este árbol ilustra nombres reales de las familias de salida; los índices
`000` y `003` pueden cambiar entre informes.

### Páginas principales y tablas auxiliares

| Archivo o patrón | Formato y contenido | Qué información extraer |
|---|---|---|
| `index.html` | Portada HTML con modelos, cantidad de instancias, enlaces y opciones de PAVER. | Alcance de la comparación, entrada usada, `failtime`, `mintime`, tolerancias y filtros configurados. |
| `documentation.html` | Documentación de las métricas incluida con PAVER. | Definiciones de medias, cuantiles, gaps y perfiles de esa instalación. |
| `solvedata.html` | Tabla HTML detallada por instancia y ejecución. | Objetivo, tiempo, terminación e iteraciones; permite localizar qué casos explican un promedio o una diferencia. |
| `raw.html` | Atributos internos de instancias y ejecuciones, después de la lectura y el procesamiento. | Valores normalizados, `Fail` y `FailReason`; útil para investigar datos ausentes o inconsistencias. |
| `stat_Status.html` | Conteos por tipo de terminación y fallas detectadas, cuando las hay. | Cuántas corridas terminaron normalmente, alcanzaron límites o tuvieron problemas. |
| `stat_SolutionQuality.html` | Estadísticas y comparaciones de calidad, habitualmente sobre `PrimalBound`. | Cuántas soluciones quedan cerca o lejos del mejor resultado observado. |
| `stat_Efficiency.html` | Estadísticas de tiempo y, si hay datos suficientes, iteraciones o nodos; contiene los gráficos. | Costo computacional, dispersión y diferencias entre algoritmos bajo cada filtro. |
| `stat_<Categoria>dataNNN.html` | Valores por instancia que alimentan una sección estadística. | Casos concretos incluidos y valores usados después de filtros, sustituciones y recortes. |
| `stat_<Categoria>ratioNNN_<referencia>.html` | Comparación por instancia con una referencia. | Ratios o diferencias relativas que explican los conteos `better`, `close` y `worse`. |
| `solvedataaggr.html` | Tabla agregada, si PAVER combina varias ejecuciones de un mismo solver. | Resultados agregados entre repeticiones; contrastar también los datos individuales. |

Los CSV `benchmark.csv`, `*_iterations.csv`, `*_phases.csv`, el JSONL del pool
y los PNG de layouts los genera **el proyecto**, no PAVER. Complementan el
informe con información del algoritmo que no está en la traza de ocho campos.

### Cómo leer los nombres

En `stat_Efficiencyboxplot000_virt.best.png`:

- `stat_` indica una salida estadística.
- `Efficiency` es la categoría; también aparecen `Status` y `SolutionQuality`.
- `boxplot` identifica el gráfico. Otras familias son `count`, `arithmean`,
  `geommean`, `sh.geommean`, `close`, `better`, `worse`, `profilerel`,
  `profileabs` y, si se habilita, `profileext`.
- `000` identifica una sección del informe, asociada a un atributo y un filtro.
  No es una instancia ni una iteración de CG. Su significado no es fijo entre corridas.
- `_virt.best` indica que se compara con el mejor solver virtual. Sin ese sufijo,
  un boxplot de tiempo muestra segundos; con él, suele mostrar ratios de tiempos.
- `.png` es la imagen utilizada por el HTML.

Para identificar un gráfico, buscarlo dentro de `stat_Efficiency.html` o la
página de su categoría y leer **atributo, filtro, unidades y referencia**.
Los enlaces `Data` llevan a los valores que justifican la tabla.

### Exportaciones opcionales

La integración automática solicita HTML y usa PNG por defecto. PAVER admite
además las siguientes opciones al regenerar un informe manualmente:

| Opción | Salida adicional |
|---|---|
| `--writetext <directorio>` | Tablas de texto: `solvedata.txt`, `attrranges.txt`, `raw.txt`, `options.txt`, `stat_<Categoria>.txt` y archivos de datos, ratios y perfiles. Si hay agregación, también `aggrsolvedata.txt` y `aggrattrranges.txt`. |
| `--figformat svg` | Gráficos SVG además de las imágenes PNG de previsualización. |
| `--figformat pdf` | Cada gráfico en PDF además del PNG. No crea un PDF único de todo el informe. |
| `--extendedprofiles` | Perfiles extendidos, con nombres `stat_<Categoria>profileextNNN.png`, cuando pueden calcularse. |

Los `.txt` son tablas de texto con espacios, no CSV. La salida habitual no
incluye un libro Excel ni un informe Markdown. Para reproducir una comparación,
conservar la traza, las opciones y el informe completo.

## Qué leer en las tablas

### Datos por instancia: `solvedata.html`

Las columnas suelen agruparse por `solver@run`; `@0` identifica una ejecución,
no una iteración del algoritmo.

| Columna visible | Cómo interpretarla |
|---|---|
| `Instance` / `name` | Instancia correspondiente a la fila. |
| `TermStatus` | Terminación; por ejemplo, `normal` o `timelim`. No equivale al estado de optimalidad del modelo. |
| `Primal bound` | Objetivo de la solución reportada. En este problema de maximización, más rectángulos es mejor. |
| `Time` | Tiempo reportado, en segundos. No implica tiempo hasta demostrar el óptimo global. |
| `Iters` | Iteraciones del método que las informa. Las iteraciones de CG no son directamente comparables con iteraciones internas de CPLEX o de backtracking. |
| `Dual bound`, `Gap` y otras columnas, si aparecen | Dependen de la información de entrada y de las opciones; verificar que las cotas correspondan al mismo problema. |

Primero comparar objetivos y terminaciones de una misma fila; después, sus
tiempos. Un algoritmo puede terminar antes y devolver menos rectángulos.
`NA`, `NaN`, `--` o `-` indican ausencia de información según el archivo.
`inf` y `-inf` pueden representar cotas o marcadores internos de ausencia;
no son cantidades de rectángulos. Volver a la traza y a los CSV para resolver
una duda, sin reemplazar un objetivo ausente por cero.

### Estado: `stat_Status.html`

`normal termination` cuenta terminaciones normales y `exceeded some limit`
cuenta límites de tiempo, nodos, iteraciones u otros límites. Si existen, otras
secciones muestran interrupciones, problemas de capacidad, errores y corridas
marcadas como fallidas.

Estos conteos describen **cómo terminó la ejecución**. Una terminación normal
puede corresponder a una solución factible, a un modelo restringido óptimo o a
otro resultado. Un límite puede conservar una buena solución factible.
Para decidir qué ocurrió, consultar también `ModelStatus` en la traza,
el objetivo y el diagnóstico del algoritmo.

### Medias, dispersión y cuantiles: `stat_Efficiency.html`

| Fila | Qué mide | Qué permite observar |
|---|---|---|
| `count` | Cantidad de datos disponibles bajo ese filtro y tratamiento de valores ausentes. | Base de la comparación. Si los conteos difieren, las medias pueden usar conjuntos distintos. |
| `arith. mean` | Media aritmética. | Costo promedio; los casos muy lentos tienen mucho peso. |
| `arith. std.` | Desviación estándar aritmética. | Dispersión entre instancias, en las unidades del atributo. |
| `geom. mean` | Media geométrica. | Comportamiento multiplicativo; útil cuando los tiempos abarcan varios órdenes de magnitud. |
| `geom. std.` | Dispersión geométrica. | Variación multiplicativa; no se interpreta como segundos adicionales. |
| `sh.geom. mean` | Media geométrica desplazada. | Resumen de tiempos con menor sensibilidad a valores casi nulos; depende del desplazamiento informado. |
| `sh.geom. std.` | Dispersión de los valores desplazados en escala geométrica. | Variabilidad asociada a ese resumen; tampoco está en segundos. |
| `min` / `max` | Menor y mayor valor del conjunto. | Casos extremos, incluidos recortes o penalizaciones si se aplicaron. |
| `25.0%`, `50.0%`, `75.0%` | Cuartiles; `50.0%` es la mediana. | Caso central y amplitud de la mitad central de los datos. |
| `90.0%` | Percentil 90. | Comportamiento de la parte más lenta, además del caso típico. |

Para valores `v_i`, la media geométrica desplazada con parámetro `s` es:

```text
exp(promedio(log(v_i + s))) - s
```

En la configuración estándar de PAVER, `timeshift=10` para los tiempos;
confirmarlo en `index.html` y en la nota `geometric mean shift` de la sección.
Comparar esa media solo con el mismo desplazamiento y protocolo.
Una mediana baja con un percentil 90 alto indica muchos casos rápidos y una
cola de casos difíciles. Esa dispersión entre instancias no mide variabilidad
entre semillas: para eso hacen falta repeticiones de las mismas instancias.

### Referencias virtuales y comparación relativa

`virt. best` elige el mejor valor **por instancia y por atributo** entre los
algoritmos incluidos. Para tiempo, elige el menor; para cantidad de rectángulos,
el mayor. `virt. worst` representa el peor, sujeto a disponibilidad de datos.
No son algoritmos ejecutables, y el mejor tiempo y el mejor objetivo pueden
provenir de métodos diferentes. En los nombres de archivo aparecen sin espacios:
`virt.best` y `virt.worst`.

En una tabla de ratios de tiempo respecto de `virt. best`:

```text
ratio = tiempo_del_algoritmo / menor_tiempo_de_la_instancia
```

`1` significa igualar el mejor tiempo; `2`, tardar el doble; `10`, diez veces
ese tiempo. La media de estos ratios no equivale al cociente de las medias
de tiempo. Para objetivos positivos de maximización, un ratio objetivo/mejor
objetivo cercano a `1` indica mayor cercanía al mejor resultado observado.
En ciertos atributos, cuando no se calculan ratios, el archivo `ratio...`
contiene diferencias relativas: revisar el atributo y la tabla que lo enlaza.

| Fila o gráfico | Significado respecto de la referencia |
|---|---|
| `better` | Cantidad de casos con mejora que alcanza las tolerancias configuradas. |
| `close` | Casos que no se clasifican como mejores ni peores según esas tolerancias. |
| `worse` | Casos con deterioro que alcanza las tolerancias configuradas. |

`close` no significa igualdad exacta ni optimalidad. La configuración estándar
usa tolerancia relativa `0.1` para tiempos y objetivos; en tiempos agrega la
absoluta `mintime`. Si ambas están presentes, la diferencia debe alcanzar ambas
para clasificarse como mejor o peor. La diferencia relativa usada aquí se
normaliza por `max(1, abs(valor), abs(referencia))` y no coincide necesariamente
con un gap respecto de la literatura. Leer las tolerancias impresas en cada bloque.

Por ejemplo, con mejor objetivo `20`, obtener `19` puede contarse como `close`
con tolerancia `0.1`, aunque falte un rectángulo. Para contar coincidencias
exactas, usar los objetivos por instancia. Frente a `virt. best`, `better`
debe ser cero por definición; `close` indica cercanía según la tolerancia.

### Filtros y tratamiento de límites

Cada bloque tiene su propio `Filter`. Los más habituales son:

| Filtro | Casos incluidos |
|---|---|
| `all instances` | Todas las instancias para ese análisis, con las sustituciones indicadas. |
| `no fail` | Datos no marcados como fallidos para cada solver. Puede cambiar el conjunto entre algoritmos. |
| `no fail by all solver` | Instancias sin fallas detectadas para ninguno de los algoritmos. |
| `time >= 10.0 by at least one solver and no fail for all solvers` | Subconjunto sin fallas en todos los algoritmos en el que al menos uno tardó 10 segundos o más. El umbral depende de `filtertime`. |

`Fail=False` expresa el resultado de los controles de PAVER; **no acredita
optimalidad ni verifica por sí solo la geometría del packing**. Un `TimeLimit`
no se marca automáticamente como falla en la configuración estándar, por lo
que puede aparecer dentro de `no fail`.

La sección puede indicar, por ejemplo:

```text
Attribute values were projected onto interval [0.001, 1200.0].
Missing values and values for failed instances substituted by 1200.0.
```

Esto significa que las estadísticas usan tiempos recortados a ese intervalo
y sustituyen faltantes o fallas por `failtime`. Un tiempo real de `1200.4`
puede entrar como `1200`; consultar `solvedata.html` o la traza para el valor
reportado originalmente. Los casos con límite conservan su estado de límite.
Estas transformaciones también afectan ratios, medias, boxplots y perfiles.

Comparar el bloque de todas las instancias junto con los bloques filtrados.
Informar siempre cuántos casos entran: excluir los problemas difíciles o usar
`failtime` distinto puede cambiar la conclusión.

## Qué información sacar de los gráficos

### Barras de conteos, medias y comparaciones

| Patrón del PNG | Qué muestra | Qué concluir de él |
|---|---|---|
| `*countNNN.png` | Número de casos que cumplen un filtro, por ejemplo terminación normal. | Frecuencia del evento; relacionarla con el total de instancias. |
| `*arithmeanNNN.png` | Media aritmética del atributo. | Para tiempo, barras más bajas indican menor costo promedio bajo ese filtro. |
| `*geommeanNNN.png` / `*sh.geommeanNNN.png` | Medias geométricas, sin desplazamiento o con él. | Resumen complementario del costo; mantener iguales filtros y desplazamiento. |
| `*betterNNN_<ref>.png` | Casos mejores que la referencia según tolerancias. | Ventajas detectadas respecto de esa referencia. |
| `*closeNNN_<ref>.png` | Casos cercanos a la referencia según tolerancias. | Cobertura de resultados considerados similares. |
| `*worseNNN_<ref>.png` | Casos peores que la referencia según tolerancias. | Frecuencia de desventajas. |

Una etiqueta `8 / 12` en los gráficos de comparación indica ocho casos de doce,
no un valor de objetivo ni ocho segundos. Las barras de medias resumen los
datos; consultar la tabla o el boxplot para conocer su dispersión.

### Boxplots: `*boxplotNNN*.png`

El eje horizontal identifica algoritmos y el vertical el atributo o su ratio.
La línea dentro de la caja es la mediana; la caja va del percentil 25 al 75.
Los bigotes llegan a los datos extremos dentro de 1.5 veces el rango
intercuartílico desde cada borde; los puntos restantes son valores atípicos.

Para tiempo, una mediana baja muestra menor tiempo central y una caja estrecha,
menor dispersión central entre instancias. Una caja estrecha puede coexistir
con casos muy lentos fuera de ella. Los atípicos merecen revisión por instancia;
no son necesariamente errores. Si el archivo termina en `_virt.best`, leer el
eje como ratio cuando corresponda: una mediana `2` significa que el ratio de
tiempo central es dos, no que la mediana de tiempo sea dos segundos.

### Perfil absoluto: `*profileabsNNN.png`

Para `SolverTime`, el eje X es un umbral de tiempo en segundos. El eje Y de
esta versión de PAVER es la **cantidad acumulada de instancias** cuyo tiempo
usado en el análisis no supera el umbral, bajo el filtro indicado.

Por ejemplo, si en `x=60` la curva alcanza `y=18`, hay 18 casos con tiempo
analizado menor o igual a 60 segundos. Si el filtro contiene 30 instancias,
es el 60% de ese conjunto. Una curva más alta a igual tiempo indica mayor
cobertura de casos dentro de ese presupuesto.

Antes de llamarlos «casos resueltos», verificar el criterio de éxito: con
recortes y sustituciones a `failtime`, una subida al final puede incluir
límites o fallas penalizadas. El perfil de tiempo por sí solo no establece
que se obtuviera una solución óptima, ni siquiera un entero disponible en CG.

### Perfil relativo: `*profilerelNNN.png`

Para tiempos, el eje X es el factor respecto del menor tiempo de cada instancia:

```text
r(instancia, algoritmo) = tiempo(instancia, algoritmo)
                         / min_algoritmos(tiempo(instancia, algoritmo))
Y(tau) = cantidad de instancias con r <= tau, bajo el filtro indicado
```

- Cerca de `x=1`, la altura muestra cuántos casos igualan el mejor tiempo.
- En `x=2`, muestra cuántos tardan como máximo el doble del mejor.
- En `x=10`, cuántos tardan como máximo diez veces el mejor.

Si `Y(2)=24` sobre 30 casos, el algoritmo queda dentro de un factor dos del
mejor en el 80% de ese conjunto. Una curva más alta para un mismo factor muestra
mayor cobertura relativa. Si las curvas se cruzan, la preferencia depende del
factor aceptable; no hay un ganador único para todos los umbrales.

El eje X suele ser logarítmico: distancias iguales representan factores, no
sumas iguales de segundos. La altura final cuenta valores admitidos por el
análisis y su filtro, no certificaciones de óptimo. Con penalizaciones finitas,
las curvas pueden terminar todas en el total aunque existan fallas o límites.

### Perfil extendido, si se solicita: `*profileextNNN.png`

Compara el tiempo de cada algoritmo contra el mejor tiempo de los **otros**
algoritmos, excluyéndolo del denominador. Por eso puede haber ratios menores
que uno, que indican ventaja frente a todos los competidores. No mezclar su
lectura con la del perfil relativo habitual, que incluye al propio algoritmo.

## Qué llevar del informe a una comparación experimental

| Pregunta | Dónde buscar | Qué registrar |
|---|---|---|
| ¿Qué calidad final alcanza cada algoritmo? | `solvedata.html`, `stat_SolutionQuality.html` y CSV del benchmark. | Objetivo por instancia, cantidad de coincidencias exactas con una referencia y casos sin solución. |
| ¿Cuánto cuesta obtener ese resultado? | `stat_Efficiency.html`, medias, boxplots y perfiles. | Mediana, media geométrica desplazada con su parámetro, percentil 90 y cobertura temporal. |
| ¿Con qué frecuencia alcanza un límite o falla? | `stat_Status.html`, traza y `raw.html`. | Conteos separados de límites, errores, ausencia de solución y terminaciones normales. |
| ¿En qué casos cambia el comportamiento? | Enlaces `Data` y archivos `ratio...`. | Instancias que explican pérdidas de calidad, ratios altos o atípicos. |
| ¿Por qué cambia el rendimiento de CG? | CSV de iteraciones/fases y JSONL del pool. | Tiempo de maestro y pricing, columnas generadas y evidencia de cierre; la traza PAVER no contiene ese detalle. |

Una redacción reproducible debe indicar conjunto de instancias, hardware,
presupuesto, semillas, hilos, configuración de cada algoritmo, filtro,
tolerancias y tratamiento de faltantes. Informar mejoras de tiempo junto con
calidad y estados. Los perfiles describen el conjunto medido; no garantizan
el mismo comportamiento en otras familias de instancias.

Para interpretar estos resultados en el problema del proyecto:

- Se maximiza la cantidad de rectángulos idénticos en un solo contenedor.
  Una mayor cantidad factible representa mejor calidad.
- Los modelos con y sin rotación tienen distintos espacios factibles. Mantener
  su identificación y aclarar esa diferencia al comparar calidad y tiempo.
- La terminación normal y `ModelStatus=1` se refieren al modelo resuelto.
  Un maestro entero óptimo sobre el pool generado no certifica por sí solo
  el óptimo global del packing.
- El último LP restringido no es una cota superior del maestro completo si
  falta evidencia de cierre. Revisar `lp_convergence_proven` y su diagnóstico.
- `virt. best` es el mejor valor observado entre los algoritmos del informe.
  No es automáticamente la referencia de literatura ni una prueba de óptimo.
- La integración usa `--ignoredualbounds`; no interpretar el informe como una
  comparación de certificados duales globales. La referencia de literatura se
  conserva en el benchmark, pero no se transmite en la traza de ocho campos.
- Una solución entera ausente permanece ausente. La factibilidad geométrica,
  el objetivo LP, el entero restringido y la referencia son evidencias distintas.

Las convenciones de tablas y gráficos se pueden contrastar con la
[documentación de PAVER](https://github.com/coin-or/Paver/blob/master/src/paver/documentation.html)
y su [implementación de estadísticas](https://github.com/coin-or/Paver/blob/master/src/paver/solvestat.py).
El [repositorio oficial](https://github.com/coin-or/Paver) identifica la herramienta
y su publicación de referencia. En el proyecto, el fixture
[paver_smoke.txt](../tests/fixtures/paver_smoke.txt) permite comprobar el lector
de trazas sin resolver nuevos modelos de optimización.
