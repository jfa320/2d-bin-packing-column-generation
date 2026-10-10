# Empaquetado bidimensional monoítem con generación de columnas

Este proyecto estudia el Manufacturer's Pallet Loading Problem (MPLP): ubicar la mayor cantidad posible de ítems rectangulares idénticos en un único bin rectangular, sin solapamientos. El modelo principal permite rotación de 90°; los modelos de comparación incluyen variantes con y sin rotación.

## Contexto del proyecto

Este repositorio contiene la implementación desarrollada en el marco de una tesina de grado para la culminación de la Licenciatura en Sistemas de la Universidad Nacional de General Sarmiento.

El trabajo aborda el empaquetado bidimensional monoítem mediante un enfoque de generación de columnas. El modelo principal se compone de un problema maestro de selección de rebanadas, un problema de pricing para generar nuevas rebanadas y una resolución entera final utilizando las columnas generadas.

## Enfoque del proyecto actual

La resolución se basa en generación de columnas. El problema se descompone en un modelo maestro y un modelo esclavo:

- El modelo maestro selecciona rebanadas ya generadas y controla que no haya colisiones entre los ítems elegidos.
- El modelo esclavo usa la información dual del maestro para generar nuevas rebanadas candidatas que puedan mejorar la solución actual.
- El proceso se repite mientras aparezcan rebanadas nuevas con potencial de mejora. Al finalizar, el maestro se resuelve en versión entera con las columnas generadas.

El maestro LP se actualiza incrementalmente; si la actualización falla, se reconstruye desde el pool. El maestro entero final se construye de nuevo y utiliza únicamente las columnas generadas. Esta resolución no garantiza por sí sola el óptimo entero del problema original.

Las heurísticas de alternativas con cortes, exploración de columnas cercanas a cero y segunda fase del pricing están desactivadas por defecto (`USE_PRACTICAL_CG_ENHANCEMENTS=False`). El flujo base se detiene ante un duplicado positivo. La inicialización greedy uniforme propuesta por Marcelo existe como alternativa, pero no está activa. Los detalles y el diagnóstico actualizado del caso `50 x 20 / 13 x 8` están en [`docs/algorithm.md`](docs/algorithm.md).

## Modelos implementados

| Modelo | Descripción | Uso |
| --- | --- | --- |
| Generación de columnas | Modelo maestro-esclavo con generación iterativa de rebanadas | Propuesta principal de la tesina |
| Backtracking exacto | Resolución exacta adaptada a las instancias monoítem estudiadas | Comparación |
| Andrade-Birgin | Modelo de referencia adaptado a partir de la formulación de Andrade y Birgin | Comparación |
| Modelos simplificados | Modelos de la literatura adaptados al 2D-BPP monoítem estudiado en esta tesina | Comparación y validación |

Los modelos de comparación fueron adaptados a partir de formulaciones o enfoques que no coincidían exactamente con el alcance de esta tesina. En particular, algunas formulaciones originales consideran múltiples tipos de ítems, múltiples tamaños o restricciones adicionales, como prioridades entre ítems.

## Estructura del repositorio

```text
.
├── main.py
├── config.py
├── instances.py
├── models/
├── objects/
├── utils/
├── archive/
├── tests/
├── docs/
├── Results/
└── requirements.txt
```

## Requisitos

- Python 3.10
- IBM ILOG CPLEX Optimization Studio
- API de CPLEX para Python
- Una licencia válida de CPLEX
- `pip`
- `pytest`, para ejecutar tests

Este proyecto fue desarrollado utilizando IBM ILOG CPLEX Optimization Studio. La edición gratuita de CPLEX posee límites en la cantidad de variables y restricciones, por lo que puede no ser suficiente para ejecutar todas las instancias. Para instancias más grandes puede requerirse una licencia académica o comercial habilitada.

## Instalación

Crear un entorno virtual:

```bash
python -m venv .venv
```

Activarlo en Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Instalar dependencias:

```bash
python -m pip install -r requirements.txt
```

Verificar que CPLEX esté disponible:

```bash
python -c "import cplex; print(cplex.__version__)"
```

Nota: la dependencia `cplex` requiere una instalación válida de IBM ILOG CPLEX Optimization Studio y una versión de Python soportada por esa instalación. Si `pip install cplex` no funciona, instalar la API de Python desde la carpeta de instalación de CPLEX correspondiente a la versión de Python usada.

## Ejecución de instancias

El catálogo de instancias está en [`instances.py`](instances.py), con acceso mediante `get_instance` en [`config.py`](config.py). Los identificadores son `case2`, `case7`, etc. y se usan como `InputFileName` en la traza PAVER. Ejecutar los comandos desde la raíz del repositorio.

Para ejecutar el caso por defecto, alcanza con correr `main.py` directamente:

```bash
python main.py
```

El caso por defecto es `case7`, definido por `DEFAULT_CASE_NAME` en `instances.py` y expuesto mediante `config.py`. `main.py` ejecuta los cinco modelos de `MODELS` para cada instancia; no tiene un selector de modelo individual.

Para ejecutar una instancia puntual:

```bash
python main.py --case case7
```

Para ejecutar varias instancias en una misma corrida:

```bash
python main.py --cases case2 case4 case7
```

Para ejecutar todas las instancias cargadas en el catálogo:

```bash
python main.py --all
```

También se puede cambiar el tiempo límite por modelo:

```bash
python main.py --cases case2 case4 case7 --time 1200
```

El tiempo indicado es por modelo; no es un límite total de toda la corrida. La salida se guarda por defecto en `Results/output.trc`, sobrescribiendo la traza existente. `--append` agrega sólo combinaciones nuevas de instancia y modelo a una traza compatible. Se puede cambiar el nombre del archivo con:

```bash
python main.py --case case7 --output output_case7.trc
```

La ejecución normal genera el informe HTML de PAVER al finalizar:

```powershell
python main.py --all --time 1200 --output comparison.trc
```

Para omitir PAVER se usa `--no-paver`. La ruta de instalación se configura en
[`paver.properties`](paver.properties) mediante la propiedad `paver.path`. Para
una ejecución puntual puede reemplazarse con `--paver-path`; si PAVER no está
disponible, se informa el error y se conserva la traza `.trc`.

La estructura esperada para PAVER es una fila por combinación de instancia y modelo, por ejemplo:

```text
case2,Model5Orchestrator,...
case2,BacktrackingMonoitemExacto,...
case4,Model5Orchestrator,...
case4,BacktrackingMonoitemExacto,...
```

## Benchmark experimental

La ejecución del benchmark de generación de columnas está documentada en
[`docs/benchmark_paver.md`](docs/benchmark_paver.md).

Desde la raíz del repositorio, ejecutar:

```powershell
python benchmark_runner.py --input "benchmark_validation_baseline.csv" --output "Results\benchmark.csv" --trace "Results\benchmark.trc" --time 300
```

El runner procesa todas las filas del CSV de entrada y ejecuta sólo generación de columnas con `finalization_heuristics=False`. El parámetro `--time` define el límite de pared compartido por CG y el maestro entero para cada instancia. Un entero `NA` por timeout o interrupción no acredita una solución entera subóptima.
Al finalizar, ejecuta PAVER usando la ruta configurada en `paver.properties`.
El informe queda en `Results\benchmark_paver\index.html` cuando la traza se
llama `Results\benchmark.trc`.

Para generar solamente el CSV y la traza se puede usar `--no-paver`.

`--expected-count` es opcional y solo permite verificar una cantidad esperada:

```powershell
python benchmark_runner.py --input "benchmark_validation_baseline.csv" --expected-count 30 --time 300
```

El CSV experimental se escribe en `Results\benchmark.csv` y la traza
compatible con PAVER en `Results\benchmark.trc`. Se recomienda usar nombres
de salida nuevos para cada corrida.

## Ejecución de pruebas

Comprobaciones rápidas sin resolver modelos:

```bash
python -m pytest tests/test_config.py
```

Pruebas puntuales con CPLEX:

```bash
python -m pytest "tests/test_orchestrator.py::test_orchestrator_cases[case1]"
python -m pytest "tests/test_feasibility.py::test_orchestrator_solution_is_feasible[case1]"
```

La suite completa se ejecuta con `python -m pytest`. Incluye resoluciones reales de CPLEX y casos grandes. Usar un límite externo de pared para verificaciones con solver: las pruebas que llaman directamente al orquestador no pasan por el monitor de su proceso hijo.

## Algoritmo

La implementación utiliza un esquema de generación de columnas compuesto por un modelo maestro y un modelo esclavo, también denominado problema de *pricing*.

El modelo maestro selecciona las rebanadas que forman la solución y el modelo esclavo genera nuevas columnas a partir de los valores duales.

La descripción detallada, las condiciones de corte, el rol de cada modelo y el diagrama del flujo están documentados en [`docs/algorithm.md`](docs/algorithm.md).
