# Bin Packing Bidimensional resuelto con generación de columnas

Este proyecto aborda el problema de Bin Packing Bidimensional (2D-BPP), donde se busca ubicar un conjunto de ítems rectangulares dentro de un bin rectangular evitando solapamientos entre ellos y respetando las dimensiones del bin. El objetivo es construir una disposición factible que empaquete la mayor cantidad posible de ítems, considerando posiciones válidas y, según el modelo utilizado, rotación de los ítems.

## Contexto del proyecto

Este repositorio contiene la implementación desarrollada en el marco de una tesina de grado para la culminación de la Licenciatura en Sistemas de la Universidad Nacional de General Sarmiento.

El trabajo aborda el problema de Bin Packing Bidimensional mediante un enfoque de generación de columnas. El modelo principal se compone de un problema maestro de selección de rebanadas, un problema de pricing para generar nuevas rebanadas y una resolución entera final utilizando las columnas generadas.

## Enfoque del proyecto actual

La resolución se basa en generación de columnas. El problema se descompone en un modelo maestro y un modelo esclavo:

- El modelo maestro selecciona rebanadas ya generadas y controla que no haya colisiones entre los ítems elegidos.
- El modelo esclavo usa la información dual del maestro para generar nuevas rebanadas candidatas que puedan mejorar la solución actual.
- El proceso se repite mientras aparezcan rebanadas nuevas con potencial de mejora. Al finalizar, el maestro se resuelve en versión entera con las columnas generadas.

Para evitar ciclos o repeticiones, la implementación detecta rebanadas ya generadas y puede agregar restricciones de exclusión al modelo esclavo.

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
pip install -r requirements.txt
```

Verificar que CPLEX esté disponible:

```bash
python -c "import cplex; print(cplex.__version__)"
```

Nota: la dependencia `cplex` requiere una instalación válida de IBM ILOG CPLEX Optimization Studio y una versión de Python soportada por esa instalación. Si `pip install cplex` no funciona, instalar la API de Python desde la carpeta de instalación de CPLEX correspondiente a la versión de Python usada.

## Ejecución de instancias

Las instancias se configuran en [`config.py`](config.py). Cada instancia tiene un nombre propio (`caso2`, `caso7`, etc.) que se usa como `InputFileName` en el archivo `.trc` de PAVER.

Para ejecutar el caso por defecto, alcanza con correr `main.py` directamente:

```bash
python main.py
```

El caso por defecto se define en `config.py` mediante `DEFAULT_CASE_NAME`.

Para ejecutar una instancia puntual:

```bash
python main.py --case caso7
```

Para ejecutar varias instancias en una misma corrida:

```bash
python main.py --cases caso2 caso4 caso7
```

Para ejecutar todas las instancias cargadas en el catálogo:

```bash
python main.py --all
```

También se puede cambiar el tiempo límite por modelo:

```bash
python main.py --cases case2 case4 case7 --time 1200
```

La salida se guarda por defecto en `Results/output.trc`. Se puede cambiar el nombre del archivo con:

```bash
python main.py --case case7 --output output_case7.trc
```

La estructura esperada para PAVER es una fila por combinación de instancia y modelo, por ejemplo:

```text
caso2,Model5Orchestrator,...
caso2,BacktrackingMonoitemExacto,...
caso4,Model5Orchestrator,...
caso4,BacktrackingMonoitemExacto,...
```

## Ejecución de pruebas

```bash
pytest
```

## Algoritmo

La implementación utiliza un esquema de generación de columnas compuesto por un modelo maestro y un modelo esclavo, también denominado problema de *pricing*.

El modelo maestro selecciona las rebanadas que forman la solución y el modelo esclavo genera nuevas columnas a partir de los valores duales.

La descripción detallada, las condiciones de corte, el rol de cada modelo y el diagrama del flujo están documentados en [`docs/algorithm.md`](docs/algorithm.md).
