# Generación múltiple: diagnóstico y variante optativa

El objetivo es evaluar si varias columnas útiles por pricing amortizan su costo.
Los parámetros citados como `solnpoolintensity` y `solnpoolcapacity` se llaman
`parameters.mip.pool.intensity` y `parameters.mip.pool.capacity` en la API Python.
Los valores iniciales no constituyen una conclusión de rendimiento.

## Activar o desactivar B desde config.py

```python
USE_PRACTICAL_CG_ENHANCEMENTS = False
USE_PRICING_SOLUTION_POOL = True  # False: una columna por iteración
```

`USE_PRICING_SOLUTION_POOL=True` activa B en el orquestador y en las ejecuciones
normales de `main.py`: hasta cinco columnas útiles por iteración, capacidad 20,
intensidad 1 y sin búsqueda adicional con `populate`. El valor actual es `True`.
Con `False` no se configura ni se lee el pool, salvo que se soliciten opciones
explícitas por API. La mejora observada es de rendimiento y cobertura; no
garantiza cerrar las brechas con el óptimo entero ni implica que los parámetros
sean óptimos.

La API permite sobrescribir el flag por ejecución con `use_pricing_pool=True`
o `False`, sin editar la configuración. `pool_options` explícitas prevalecen
sobre el flag global; `use_pricing_pool=False` desactiva incluso esas opciones.
`PricingPoolOptions(max_columns=1)` conserva también el control de una columna.
La selección se resuelve en el proceso padre y se transmite al hijo en Windows.

B conserva el alcance evaluado: requiere las heurísticas de finalización
desactivadas. Si se activan ambos mecanismos, la ejecución informa un error con
la configuración a corregir; no desactiva ninguno silenciosamente. Con B activa
se usan los duales originales y se omite la segunda fase del pricing.

El benchmark mantiene `--pool-mode off` como default, independientemente del
booleano. Para medir B allí se usa `--pool-mode passive --pool-columns 5
--pool-capacity 20`. El diagnóstico de fase 0 fuerza una columna para conservar
su trayectoria de control.

## Fase 0: observar sin agregar columnas

Desde la raíz del repositorio:

```powershell
python pricing_pool_preflight.py --cases case1 IB_004 case18 --repeats 3 --time 60 --replay-time 30 --wall-timeout 100
```

Cada corrida observa una trayectoria de una columna y la compara con un
control. No incorpora candidatos adicionales al master ni asigna IDs a sus
ítems/rebanadas. Ambos usan un hilo, la semilla seleccionada, intensidad 1,
capacidad 20 y búsqueda fría. `--seeds 1 2 3` permite variar las semillas.

Luego reproduce duales iniciales, intermedios, de la última iteración positiva
y del cierre en otro pricing reutilizado. Estos replays tienen presupuesto
separado: no son tiempo total de la trayectoria ni establecen una aceleración.
En el replay con populate se configura intensidad 2 antes del solve principal.

`--populate-time` y `--populate-ratio` controlan el presupuesto solicitado a
populate. Los defaults son 0,1 s y 0,1 del tiempo principal para reproducir
la propuesta inicial; para calibrar con un presupuesto menos restrictivo:

```powershell
python pricing_pool_preflight.py --cases IB_004 case18 --populate-time 1 --populate-ratio 1
```

La herramienta crea un directorio nuevo en `Results/`, con manifiesto de
versiones y hashes, JSON por corrida, snapshots de duales y claves del master,
resumen y comprobación exacta de trayectorias. Conserva avances ante timeout.
Los hashes finales detectan cambios de fuentes durante la ejecución; una
corrida así es exploratoria y debe repetirse antes de congelar parámetros.

La extracción diagnóstica reconstruye las claves del master en cada iteración;
su costo no estima el de la variante integrada, que mantiene ese registro.
Un pool pequeño a intensidad 1 no descarta la búsqueda deliberada con populate.

## Comparación con lotes incorporados al master

Preparar un CSV con las instancias elegidas y el formato del baseline. Usar
salidas nuevas para cada combinación y repetir con semillas 1, 2 y 3, alternando
el orden de ejecución. Ejemplos para la semilla 1:

```powershell
python benchmark_runner.py --input Results/pool_input.csv --output Results/pool_one_s1.csv --time 60 --pool-mode passive --pool-columns 1 --seed 1 --threads 1 --no-paver --detailed-csv
python benchmark_runner.py --input Results/pool_input.csv --output Results/pool_passive_s1.csv --time 60 --pool-mode passive --pool-columns 5 --pool-capacity 20 --seed 1 --threads 1 --no-paver --detailed-csv
python benchmark_runner.py --input Results/pool_input.csv --output Results/pool_populate_s1.csv --time 60 --pool-mode populate --pool-columns 5 --pool-capacity 20 --populate-time 1 --populate-ratio 1 --populate-limit 20 --seed 1 --threads 1 --no-paver --detailed-csv
```

El benchmark conserva el límite global para preparación, CG y entero, sin una
nueva reserva para IP. Un entero ausente por corte se informa como ausente,
no como cero. El tiempo de exportación y el inicio del proceso forman parte
del tiempo de pared y pueden dominar instancias diminutas.

Los CSV principal, de iteraciones y de fases conservan su esquema. Al pasar
`--pool-mode`, se agrega `<nombre>_pool.jsonl`: una línea por instancia con
configuración, semilla/hilos, versiones, hashes y resultado estructurado completo,
incluidas las métricas adicionales y los descartes por iteración. Este archivo
también queda protegido contra sobrescrituras accidentales. `--pool-mode off`
es el default y no produce ese archivo adicional.

La opción `--pool-intensity` permite fijar explícitamente la intensidad.
Una columna desactiva la extracción y configuración del pool incluso si se
creó un objeto de opciones, de modo que sirve como control de referencia.

## API

```python
from models.column_generation.column_generation_solver import execute_with_time_limit
from models.column_generation.solution_pool import PricingPoolOptions
from config import get_instance

if __name__ == "__main__":  # necesario para multiprocessing en Windows
    result = execute_with_time_limit(
        60, instance=get_instance("case18"), finalization_heuristics=False,
        random_seed=1, threads=1,
        pool_options=PricingPoolOptions(max_columns=5, mode="passive", capacity=20),
    )
    print(result.metrics)
    print(result.diagnostics)
```

## Interpretación y alcance

Comparar tiempo total y CG, entero factible, cierre LP, llamadas y crecimiento
del master. Menos iteraciones no prueba una mejora. El LP sin cierre no es
una cota superior del master completo, y el entero restringido no certifica
por sí solo optimalidad global. Las muestras de calibración y las corridas
de comprobación no sustituyen la comparación definitiva del ticket.
