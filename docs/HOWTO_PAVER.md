# Uso de PAVER

PAVER transforma las trazas `.trc` en informes HTML para comparar resultados,
estados y tiempos. En este proyecto, `SolverName` identifica el enfoque
algorítmico aplicado a cada instancia. El formato de la traza y la definición
de las métricas están en [benchmark_paver.md](benchmark_paver.md).

## Configuración

La copia externa debe contener `src/paver/paver.py`. Configurar su directorio
raíz en [paver.properties](../paver.properties):

```properties
paver.path=I:\Mi unidad\Tesina\Paver
```

Esta ruta corresponde a la instalación local y debe ajustarse en otra máquina.
La integración de [paver_runner.py](../utils/paver_runner.py) usa `py -3.6`,
con las dependencias de esa instalación. El solver del proyecto usa Python
3.10 y CPLEX en su propio entorno.

Para comprobar la instalación desde PowerShell:

```powershell
$paverRoot = 'I:\Mi unidad\Tesina\Paver'
py -3.6 "$paverRoot\src\paver\paver.py" --help
```

## Generar informes

Desde la raíz del repositorio:

```powershell
python main.py --all --time 1200 --output comparison.trc
```

El comando ejecuta los cinco modelos y luego genera
`Results/comparison_paver/index.html`. Para omitir el informe, agregar
`--no-paver`. Para reemplazar la configuración en una ejecución:

```powershell
python main.py --cases case2 case4 --time 1200 --output comparison.trc --paver-path "D:\Paver" --paver-output "Results/comparison_paver"
```

`benchmark_runner.py` también genera el informe al terminar; sus opciones
están en la [guía de benchmark](benchmark_paver.md#ejecución). Si PAVER falla
o no está disponible, se conservan los resultados y la traza.

Para regenerar solo el HTML de una traza existente, desde la raíz del
repositorio, con la instalación local configurada arriba:

```powershell
$tracePath = (Resolve-Path -LiteralPath 'Results/comparison.trc').Path
$reportPath = Join-Path (Get-Location).Path 'Results/comparison_paver'
Push-Location -LiteralPath $paverRoot
try {
    py -3.6 src/paver/paver.py $tracePath --ignoredualbounds --mintime 0.001 --failtime 1200 --writehtml $reportPath
} finally {
    Pop-Location
}
```

| Opción | Uso en el proyecto |
|---|---|
| `--failtime` | Debe coincidir con el límite temporal del experimento. |
| `--mintime 0.001` | Evita problemas estadísticos con tiempos nulos o muy pequeños; no modifica los tiempos medidos en la traza. |
| `--ignoredualbounds` | Evita comparar cotas duales de enfoques con espacios de soluciones diferentes, como modelos con y sin rotación. |
| `--writehtml` | Directorio de salida del informe. |

La integración automática aplica esas opciones y toma `failtime` del
argumento `--time` de la corrida.

## Leer el informe

| Página | Qué consultar |
|---|---|
| `index.html` | Resumen y acceso al resto del informe. |
| `stat_Status.html` | Terminaciones normales, límites y errores. |
| `solvedata.html` | Objetivo, tiempo y estado por par instancia/modelo. |
| `stat_SolutionQuality.html` | Cantidad de ítems obtenida para cada instancia. |
| `stat_Efficiency.html` y perfiles | Tiempos y proporción de instancias resueltas bajo distintos factores de tiempo. |

`virt.best` es una referencia virtual que toma el mejor resultado por
instancia; no es un algoritmo ejecutable. Las medias y los perfiles dependen
del conjunto de casos y del tratamiento de límites, por lo que conviene
comparar corridas con las mismas instancias y presupuesto.

PAVER informa optimalidad del modelo resuelto. Un maestro entero óptimo sobre
un pool restringido puede producir menos ítems que otro enfoque. Para evaluar
el packing, revisar objetivo, factibilidad y referencia; una terminación
normal o un LP igual a la referencia no reemplazan esa comprobación.

El fixture [paver_smoke.txt](../tests/fixtures/paver_smoke.txt) permite probar
localmente el lector de trazas sin ejecutar nuevos modelos de optimización.
