# Bin Packing Bidimensional resuelto con generación de columnas

Este proyecto aborda el problema de Bin Packing Bidimensional (2D-BPP), donde se busca ubicar un conjunto de items rectangulares dentro de un bin rectangular evitando solapamientos entre ellos y respetando las dimensiones del bin. El objetivo es construir una disposicion factible que empaquete la mayor cantidad posible de items, considerando posiciones validas y, segun el modelo utilizado, rotación de los items.

## Enfoque del proyecto actual

La resolucion se basa en generacion de columnas. El problema se descompone en un modelo maestro y un modelo esclavo:

- El modelo maestro selecciona rebanadas ya generadas y controla que no haya colisiones entre los items elegidos.
- El modelo esclavo usa la informacion dual del maestro para generar nuevas rebanadas candidatas que puedan mejorar la solucion actual.
- El proceso se repite mientras aparezcan rebanadas nuevas con potencial de mejora. Al finalizar, el maestro se resuelve en version entera con las columnas generadas.

Para evitar ciclos o repeticiones, la implementacion detecta rebanadas ya generadas y puede agregar restricciones de exclusion al modelo esclavo.

## Requisitos

- Python 3.10
- IBM ILOG CPLEX Optimization Studio
- API de CPLEX para Python
- Una licencia valida de CPLEX
- `pip`
- `pytest`, para ejecutar tests

Este proyecto fue desarrollado utilizando IBM ILOG CPLEX Optimization Studio. La edicion gratuita de CPLEX posee limites en la cantidad de variables y restricciones, por lo que puede no ser suficiente para ejecutar todas las instancias. Para instancias mas grandes puede requerirse una licencia academica o comercial habilitada.

## Instalacion

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

Verificar que CPLEX este disponible:

```bash
python -c "import cplex; print(cplex.__version__)"
```

Nota: la dependencia `cplex` requiere una instalacion valida de IBM ILOG CPLEX Optimization Studio y una version de Python soportada por esa instalacion. Si `pip install cplex` no funciona, instalar la API de Python desde la carpeta de instalacion de CPLEX correspondiente a la version de Python usada.

Ejecutar tests:

```bash
pytest
```

## Algoritmo

La descripcion detallada del algoritmo, las condiciones de corte y el rol de cada modelo estan documentados en [`Docs/algorithm.md`](Docs/algorithm.md).

## Ejecucion de instancias

Las instancias se configuran en [`Config.py`](Config.py). Cada instancia tiene un nombre propio (`caso2`, `caso7`, etc.) que se usa como `InputFileName` en el archivo `.trc` de PAVER.

Para ejecutar el caso por defecto, alcanza con correr `Main.py` directamente:

```bash
python Main.py
```

El caso por defecto se define en `Config.py` mediante `DEFAULT_CASE_NAME`.

Para ejecutar una instancia puntual:

```bash
python Main.py --case caso7
```

Para ejecutar varias instancias en una misma corrida:

```bash
python Main.py --cases caso2 caso4 caso7
```

Para ejecutar todas las instancias cargadas en el catalogo:

```bash
python Main.py --all
```

Tambien se puede cambiar el tiempo limite por modelo:

```bash
python Main.py --cases caso2 caso4 caso7 --time 1200
```

La salida se guarda por defecto en `Resultados/output.trc`. Se puede cambiar el nombre del archivo con:

```bash
python Main.py --case caso7 --output output_caso7.trc
```

La estructura esperada para PAVER es una fila por combinacion de instancia y modelo, por ejemplo:

```text
caso2,Model5Orchestrator,...
caso2,BacktrackingMonoitemExacto,...
caso4,Model5Orchestrator,...
caso4,BacktrackingMonoitemExacto,...
```
