# HOWTO --- Uso de PAVER para la comparativa de modelos de la tesina

> **Implementación vigente:** consultar `docs/benchmark_paver.md` para el
> formato actual de trazas, estados `TerminationStatus` y el runner de
> benchmark. Las secciones históricas de este documento que muestran
> `SolverStatus`, `Model1` sin distinguir rotación o tiempos redondeados no
> describen el formato actual.

> Documento de referencia para recordar qué es PAVER, cómo está
> instalado actualmente, cómo generar un informe a partir de archivos
> `.trc` y cómo interpretar las páginas y gráficos principales.
>
> **Contexto de esta tesina:** se utiliza PAVER para comparar distintos
> modelos/enfoques para instancias geométricas del problema mono-item de
> empaquetado bidimensional. Los nombres registrados como `SolverName`
> representan, en la práctica, modelos o enfoques algorítmicos
> diferentes; no necesariamente distintos solvers ejecutando una
> formulación idéntica.

------------------------------------------------------------------------

## 1. ¿Qué es PAVER?

PAVER (*Performance Analysis and Visualization for Efficient
Reproducibility*) es una herramienta para analizar y visualizar
resultados de experimentos computacionales.

Recibe archivos de resultados, por ejemplo archivos GAMS Trace (`.trc`),
y genera un informe HTML con:

-   datos detallados por instancia y modelo;
-   estado de las ejecuciones;
-   estadísticas de tiempo;
-   medias aritméticas, geométricas y geométricas desplazadas;
-   comparaciones respecto de un modelo virtual de referencia;
-   perfiles de rendimiento;
-   estadísticas sobre la calidad de las soluciones.

La utilidad principal en esta tesina es evitar realizar manualmente la
comparación de resultados y tiempos. Cada modelo se ejecuta sobre el
mismo conjunto de instancias, se registran los resultados en un `.trc` y
PAVER construye las estadísticas y visualizaciones.

### Idea general

``` text
Modelos de la tesina
        |
        v
    output.trc
        |
        v
      PAVER
        |
        v
Informe HTML + gráficos PNG
```

------------------------------------------------------------------------

## 2. ¿Dónde vive PAVER actualmente?

La copia de PAVER utilizada en la tesina se encuentra en:

``` text
I:\Mi unidad\Tesina\Paver
```

El programa obtiene esta ubicación desde el archivo `paver.properties` de la
raíz del repositorio, usando la propiedad `paver.path`. El argumento
`--paver-path` queda disponible únicamente como reemplazo para una ejecución
puntual.

La estructura relevante es:

``` text
Paver
├── examples
├── solu
└── src
    └── paver
        ├── paver.py
        ├── setupdefault.py
        ├── metric.py
        ├── solvestat.py
        └── ...
```

El archivo principal es:

``` text
I:\Mi unidad\Tesina\Paver\src\paver\paver.py
```

PAVER **no está agregado globalmente al PATH**. Por eso el comando:

``` cmd
paver --help
```

no funciona.

Se ejecuta directamente mediante el script `paver.py`.

------------------------------------------------------------------------

## 3. Python que debe utilizarse

En la PC existen actualmente estas versiones de Python:

``` text
Python 3.10
Python 3.9
Python 3.6
```

PAVER funciona con el entorno de **Python 3.6** ya instalado en la
máquina.

Para ejecutarlo se debe usar:

``` cmd
py -3.6
```

No utilizar simplemente:

``` cmd
python
```

porque actualmente ese comando apunta a Python 3.10 y el entorno
correspondiente no contiene las dependencias utilizadas por esta
instalación de PAVER.

### Validar que PAVER sigue funcionando

Entrar a la carpeta:

``` cmd
cd /d "I:\Mi unidad\Tesina\Paver"
```

Ejecutar:

``` cmd
py -3.6 src\paver\paver.py --help
```

Si PAVER funciona correctamente debe mostrar una ayuda que comienza
aproximadamente con:

``` text
reading setup file src\paver\setupdefault.py
usage: paver.py [-h] ...
```

------------------------------------------------------------------------

## 4. Formato del archivo `.trc`

El programa de la tesina genera archivos con esta estructura:

``` text
* Trace Record Definition
* InputFileName,SolverName,ModelStatus,SolverStatus,ObjectiveValue,SolverTime
caso2,Model5Orchestrator,1,1,4.0,1.38
caso2,Model1,1,1,4.0,0.07
caso2,AndradeBirginBigM,1,1,4.0,0.004518032073974609
caso2,BacktrackingMonoitemExacto,1,1,4,0.0
caso4,Model5Orchestrator,1,1,3.0,0.76
caso4,Model1,1,1,3.0,0.02
caso4,AndradeBirginBigM,1,1,3.0,0.004549741744995117
caso4,BacktrackingMonoitemExacto,1,1,3,0.0
```

### Significado de las columnas

  -----------------------------------------------------------------------
  Columna                             Uso
  ----------------------------------- -----------------------------------
  `InputFileName`                     Nombre de la instancia. En la
                                      tesina: `caso2`, `caso4`, `caso7`,
                                      etc.

  `SolverName`                        Nombre del modelo o enfoque
                                      comparado.

  `ModelStatus`                       Estado del modelo según la
                                      convención del trace.

  `SolverStatus`                      Estado de terminación del solver.

  `ObjectiveValue`                    Valor objetivo obtenido. En esta
                                      tesina: cantidad de ítems
                                      empaquetados.

  `SolverTime`                        Tiempo de ejecución registrado para
                                      la corrida.
  -----------------------------------------------------------------------

### Regla experimental

La estructura deseada es:

``` text
una fila = una ejecución de un modelo sobre una instancia
```

Por ejemplo, para 2 instancias y 4 modelos deben existir 8 filas:

``` text
caso2 + Modelo A
caso2 + Modelo B
caso2 + Modelo C
caso2 + Modelo D

caso4 + Modelo A
caso4 + Modelo B
caso4 + Modelo C
caso4 + Modelo D
```

Para una comparativa simple no deben existir múltiples filas para la
misma combinación `instancia + modelo`, salvo que se diseñe
explícitamente un experimento con repeticiones y se adapte la
metodología para ello.

### Importante sobre `CASE_NAME`

Actualmente la configuración histórica tenía un valor fijo como:

``` python
CASE_NAME = "inst2"
```

Esto provoca que todas las corridas se registren como si correspondieran
a la misma instancia.

El nombre debe coincidir con el caso realmente ejecutado:

``` python
CASE_NAME = "caso7"
```

Por ejemplo:

``` python
CASE_NAME = "caso7"

BIN_WIDTH = 50
BIN_HEIGHT = 20
ITEM_WIDTH = 13
ITEM_HEIGHT = 8
```

A futuro conviene reemplazar los bloques comentados/descomentados por
una estructura de instancias o un ejecutor automático de benchmarks.

------------------------------------------------------------------------

## 5. El problema de los tiempos iguales a cero

Algunos algoritmos muy rápidos pueden registrar:

``` text
SolverTime = 0.0
```

Por ejemplo:

``` text
caso2,BacktrackingMonoitemExacto,1,1,4,0.0
```

Un tiempo cero es problemático para comparaciones relativas y medias
geométricas.

### Solución en PAVER: `--mintime`

Actualmente se utiliza:

``` cmd
--mintime 0.001
```

Esto hace que, **para los cálculos estadísticos de PAVER**, los tiempos
inferiores a `0.001` segundos sean proyectados a `0.001`.

Por ejemplo:

``` text
0.000 s -> 0.001 s
0.0004 s -> 0.001 s
0.0045 s -> 0.0045 s
1.380 s -> 1.380 s
```

Esto no significa que PAVER modifique el resultado original del modelo.
Ajusta el valor utilizado en las estadísticas.

### Mejora recomendada en el código

Medir los tiempos con:

``` python
import time

inicio = time.perf_counter()

# ejecución

tiempoEjecucion = time.perf_counter() - inicio
```

Si se desea evitar ceros en el `.trc`:

``` python
tiempoEjecucion = max(tiempoEjecucion, 0.001)
```

Debe mantenerse el mismo criterio de medición para todos los modelos
comparados.

------------------------------------------------------------------------

## 6. Cómo ejecutar PAVER

### Paso 1 --- Entrar a la carpeta de PAVER

``` cmd
cd /d "I:\Mi unidad\Tesina\Paver"
```

### Paso 2 --- Verificar la existencia del `.trc`

Ejemplo:

``` cmd
dir "I:\Mi unidad\Tesina\output.trc"
```

### Paso 3 --- Ejecutar PAVER

Comando utilizado actualmente:

``` cmd
py -3.6 src\paver\paver.py "I:\Mi unidad\Tesina\output.trc" --mintime 0.001 --failtime 900 --writehtml "I:\Mi unidad\Tesina\resultados\paver_casos_2_4"
```

### Significado de los parámetros

#### `--mintime 0.001`

Para las estadísticas, eleva los tiempos menores a `0.001` segundos a
ese valor mínimo.

Es especialmente importante para:

-   tiempos iguales a cero;
-   medias geométricas;
-   ratios respecto del mejor tiempo;
-   perfiles de rendimiento.

#### `--failtime 900`

Utiliza 900 segundos como tiempo asociado a corridas fallidas en las
estadísticas donde PAVER necesita asignar un tiempo a una falla.

**El valor debe coincidir con el límite temporal real definido para los
experimentos.**

Si el límite experimental cambia, este parámetro también debe revisarse.

#### `--writehtml`

Indica la carpeta donde PAVER debe generar el informe HTML.

Ejemplo:

``` text
I:\Mi unidad\Tesina\resultados\paver_casos_2_4
```

### Paso 4 --- Abrir el informe

Abrir:

``` text
I:\Mi unidad\Tesina\resultados\paver_casos_2_4\index.html
```

Desde CMD:

``` cmd
start "" "I:\Mi unidad\Tesina\resultados\paver_casos_2_4\index.html"
```

### Regenerar un informe

Si se desea eliminar primero la salida anterior:

``` cmd
rmdir /s /q "I:\Mi unidad\Tesina\resultados\paver_casos_2_4"
```

Luego volver a ejecutar PAVER.

------------------------------------------------------------------------

## 7. Cómo leer el informe

El informe probado contiene, entre otros, los archivos:

``` text
index.html
solvedata.html
raw.html
stat_Status.html
stat_Efficiency.html
stat_SolutionQuality.html
```

PAVER también genera imágenes `.png` utilizadas por las páginas HTML.

### Resumen rápido

  -----------------------------------------------------------------------
  Página                              Pregunta principal
  ----------------------------------- -----------------------------------
  `index.html`                        ¿Qué contiene el informe?

  `solvedata.html`                    ¿Qué hizo cada modelo en cada
                                      instancia?

  `stat_Status.html`                  ¿Las ejecuciones terminaron
                                      correctamente?

  `stat_Efficiency.html`              ¿Qué tan eficiente fue cada modelo
                                      en tiempo?

  `stat_SolutionQuality.html`         ¿Qué valores objetivo obtuvieron
                                      los enfoques y cómo se comparan?

  `raw.html`                          ¿Qué datos internos/procesados está
                                      utilizando PAVER?
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 8. `index.html`

Es el índice principal del informe.

Permite validar rápidamente:

-   modelos detectados;
-   cantidad de instancias;
-   secciones estadísticas generadas.

En la prueba inicial PAVER detectó cuatro enfoques:

``` text
Model5Orchestrator
Model1
AndradeBirginBigM
BacktrackingMonoitemExacto
```

y dos instancias:

``` text
caso2
caso4
```

No se deben extraer conclusiones experimentales desde `index.html`. Su
función principal es navegar el reporte y verificar que PAVER interpretó
correctamente los datos.

------------------------------------------------------------------------

## 9. `solvedata.html`

Es la tabla detallada por instancia y modelo.

Es una de las páginas más útiles para inspeccionar resultados concretos.

Permite responder preguntas como:

-   ¿qué valor objetivo obtuvo `Model5Orchestrator` en `caso7`?;
-   ¿cuánto tardó `Model1` en `caso8`?;
-   ¿qué ejecución falló?;
-   ¿los modelos obtuvieron el mismo valor objetivo?

Debe utilizarse como una **tabla maestra de inspección**.

Cuando un gráfico estadístico produce un resultado extraño, conviene
volver a `solvedata.html` y revisar las instancias concretas que
originaron el comportamiento.

------------------------------------------------------------------------

## 10. `stat_Status.html`

Resume el estado de las ejecuciones.

La pregunta principal es:

> ¿Cuántas instancias fueron resueltas/terminadas correctamente por cada
> modelo?

En la prueba de dos casos, los cuatro modelos tenían dos ejecuciones
válidas.

Con un conjunto mayor de instancias, esta página permite detectar
rápidamente que un enfoque:

-   falla;
-   no termina;
-   alcanza el límite temporal;
-   presenta estados diferentes en determinadas instancias.

Antes de comparar tiempos, conviene revisar `Status`.

Un algoritmo extremadamente rápido no es necesariamente mejor si falla
en una parte importante del conjunto de instancias.

------------------------------------------------------------------------

## 11. `stat_Efficiency.html`

Esta página compara principalmente la eficiencia computacional.

En el experimento actual, el atributo principal es:

``` text
SolverTime
```

### Proyección del intervalo

Con:

``` cmd
--mintime 0.001
--failtime 900
```

PAVER informa que los valores fueron proyectados sobre el intervalo:

``` text
[0.001, 900]
```

Esto significa:

-   tiempos menores a `0.001` se usan como `0.001`;
-   las fallas pueden recibir el valor `900` en estadísticas que
    necesiten un tiempo de penalización.

------------------------------------------------------------------------

## 12. Media aritmética (`arith mean`)

Es el promedio tradicional:

``` text
(t1 + t2 + ... + tn) / n
```

Ejemplo para `Model5Orchestrator`:

``` text
caso2 = 1.38 s
caso4 = 0.76 s
```

Entonces:

``` text
(1.38 + 0.76) / 2 = 1.07 s
```

### Interpretación

Responde:

> ¿Cuál fue el tiempo promedio del modelo?

### Limitación

Es sensible a valores extremos.

Una instancia excepcionalmente lenta puede elevar mucho el promedio.

------------------------------------------------------------------------

## 13. Media geométrica (`geom mean`)

Para dos valores:

``` text
sqrt(t1 * t2)
```

Para `n` valores:

``` text
(t1 * t2 * ... * tn)^(1/n)
```

### Interpretación

Resume el comportamiento multiplicativo/relativo de los tiempos.

Es habitual en benchmarks de optimización porque reduce la influencia de
casos extremos frente a la media aritmética.

### Relevancia para la tesina

Es una de las métricas principales a revisar cuando exista un conjunto
suficientemente grande de instancias.

Con solamente dos instancias no corresponde extraer conclusiones
generales.

------------------------------------------------------------------------

## 14. Media geométrica desplazada (`shifted geometric mean`)

PAVER también puede calcular una media geométrica desplazada.

La idea conceptual es aplicar un desplazamiento antes de calcular la
media geométrica:

``` text
tiempo + shift
```

El valor por defecto de PAVER para tiempos es visible en la ayuda:

``` text
--timeshift 10.0
```

Esta métrica reduce la sensibilidad asociada a valores extremadamente
pequeños.

No es necesario utilizarla en la tesina por obligación. Si se utiliza,
debe explicarse el desplazamiento aplicado.

------------------------------------------------------------------------

## 15. Boxplot

PAVER genera gráficos de tipo boxplot dentro de la sección de
eficiencia. En la salida actual existen archivos con nombres como:

``` text
stat_Efficiencyboxplot000.png
stat_Efficiencyboxplot000_virt.best.png
```

El boxplot sirve para observar la **distribución y dispersión de los
tiempos**.

Responde preguntas como:

-   ¿el modelo tiene tiempos consistentes?;
-   ¿existen instancias excepcionalmente lentas?;
-   ¿la mediana es representativa?;
-   ¿el comportamiento es estable o muy variable?

### Importante

Con dos instancias el boxplot aporta muy poca información.

Su utilidad aparece al trabajar con un conjunto mayor de casos.

------------------------------------------------------------------------

## 16. `virt.best`: el modelo virtualmente mejor

PAVER construye referencias virtuales.

Una de las más importantes es:

``` text
virt.best
```

No es un modelo real.

Para la comparación de tiempos, `virt.best` toma el **mejor tiempo
observado en cada instancia**.

Ejemplo:

  Instancia     Model1   Model5   Andrade   Backtracking   virt.best
  ----------- -------- -------- --------- -------------- -----------
  caso2          0.070    1.380    0.0045          0.001       0.001
  caso4          0.020    0.760    0.0045          0.001       0.001

`virt.best` puede estar formado por distintos modelos en distintas
instancias.

Ejemplo conceptual:

``` text
caso7  -> mejor Model5
caso8  -> mejor Andrade
caso9  -> mejor Model1
```

El `virt.best` combina esos tres mejores resultados.

### ¿Para qué sirve?

Permite preguntar:

> ¿Qué tan lejos está cada modelo del mejor comportamiento observado
> para cada instancia?

------------------------------------------------------------------------

## 17. Comparación relativa respecto de `virt.best`

Para tiempo, la idea central es comparar:

``` text
tiempo del modelo / mejor tiempo observado
```

Si:

``` text
virt.best = 1 segundo
Modelo A = 1 segundo
Modelo B = 2 segundos
Modelo C = 10 segundos
```

los ratios son:

``` text
A = 1
B = 2
C = 10
```

Interpretación:

``` text
A está en el mejor tiempo observado.
B tarda 2 veces el mejor tiempo.
C tarda 10 veces el mejor tiempo.
```

Esta lectura relativa permite comparar instancias con escalas temporales
muy diferentes.

------------------------------------------------------------------------

## 18. `better`, `close` y `worse`

PAVER clasifica comparaciones respecto de una referencia utilizando
tolerancias.

En la sección de eficiencia aparece, por ejemplo:

``` text
rel 10.0%, abs 0.001
```

Los parámetros y la lógica de tolerancia determinan cuándo una
diferencia es suficientemente importante para considerar un resultado:

``` text
better
close
worse
```

### Lectura conceptual

-   `better`: el modelo es significativamente mejor que la referencia
    comparada.
-   `close`: la diferencia no supera los criterios de relevancia
    configurados.
-   `worse`: el modelo es significativamente peor.

Por ejemplo, el gráfico:

``` text
worse than virt. best
```

responde:

> ¿En cuántas instancias este modelo fue clasificado como
> significativamente peor que el mejor comportamiento virtual?

### La línea `virt.worst`

Algunos gráficos incluyen una referencia virtual `virt.worst`.

Es otra construcción de PAVER y representa el comportamiento
virtualmente peor según la métrica considerada.

No debe confundirse con un modelo real.

------------------------------------------------------------------------

## 19. Performance Profiles

PAVER genera perfiles de rendimiento. En la salida actual existen, entre
otros:

``` text
stat_Efficiencyprofilerel002.png
stat_Efficiencyprofileabs002.png
```

Los perfiles de rendimiento son especialmente útiles con muchas
instancias.

### Perfil relativo

La idea general es:

-   eje X: factor de rendimiento respecto del mejor;
-   eje Y: proporción de instancias alcanzada por el modelo dentro de
    ese factor.

Ejemplo conceptual:

``` text
X = 1
```

indica el porcentaje de instancias donde el modelo fue el mejor
observado.

``` text
X = 2
```

indica el porcentaje de instancias donde el modelo tardó como máximo dos
veces el mejor tiempo.

``` text
X = 10
```

indica el porcentaje de instancias donde el modelo estuvo dentro de diez
veces el mejor tiempo.

### Cómo leer una curva

Una curva que sube rápidamente y permanece alta indica que el modelo
suele encontrarse cerca del mejor rendimiento observado.

Una curva baja o desplazada hacia la derecha indica que el modelo
necesita factores de tiempo mayores para cubrir el mismo porcentaje de
instancias.

### Importante para la tesina

Con dos instancias no tiene sentido extraer conclusiones generales de
estos perfiles.

Su valor aparecerá al ejecutar el conjunto completo de benchmarks.

------------------------------------------------------------------------

## 20. `stat_SolutionQuality.html`

Esta sección requiere una interpretación específica para la tesina.

### PAVER no entiende el 2DBPP

PAVER no sabe qué es:

-   un bin;
-   una rebanada;
-   un ítem;
-   una rotación;
-   una posición.

PAVER recibe valores numéricos.

En esta tesina, la calidad del resultado se interpreta mediante el valor
objetivo:

``` text
ObjectiveValue = cantidad de ítems empaquetados
```

Como el problema es de maximización:

``` text
mayor ObjectiveValue = mejor resultado de packing
```

Ejemplo:

``` text
Model1 -> 6 ítems
Model5 -> 7 ítems
```

Desde el punto de vista del empaquetado obtenido:

``` text
7 > 6
```

Por lo tanto, el resultado de Model5 tiene mayor calidad para esa
instancia geométrica.

------------------------------------------------------------------------

## 21. Distinción fundamental: optimalidad del modelo vs. calidad del packing

Este punto es **muy importante para interpretar correctamente los
resultados de la tesina**.

Los enfoques comparados no necesariamente definen el mismo espacio de
soluciones.

Ejemplo:

``` text
Modelo sin rotación
-> óptimo de su formulación = 6

Modelo con rotación
-> óptimo de su formulación = 7
```

Ambos modelos pueden haber sido resueltos a optimalidad.

Matemáticamente, puede ocurrir:

``` text
X_sin_rotacion ⊂ X_con_rotacion
```

y, por lo tanto:

``` text
max f(x), x en X_sin_rotacion = 6
max f(x), x en X_con_rotacion = 7
```

Esto **no significa que el modelo que obtiene 6 haya fallado**.

Significa que alcanzó el óptimo de un espacio de soluciones más
restringido.

### Consecuencia para PAVER

En esta tesina, `Solution Quality` no debe interpretarse como:

> ¿Qué modelo estuvo más cerca del óptimo de su propia formulación?

Debe interpretarse como:

> ¿Qué enfoque produjo el mejor empaquetado, medido mediante la cantidad
> de ítems empaquetados, para la misma instancia geométrica?

Por ejemplo:

  Instancia     Sin rotación   Con rotación
  ----------- -------------- --------------
  caso7                    6              7
  caso8                   14             16
  caso9                   13             13

Los valores 6 y 14 pueden ser óptimos para la formulación restringida.

Sin embargo, para comparar la calidad del packing producido:

``` text
caso7: 7 es mejor que 6
caso8: 16 es mejor que 14
caso9: ambos enfoques producen la misma calidad
```

### Redacción recomendada para la tesina

Una posible explicación es:

> Se evalúa la calidad de las soluciones obtenidas por los distintos
> enfoques a partir del valor de la función objetivo alcanzado para cada
> instancia. Dado que el problema considerado es de maximización, un
> mayor número de ítems empaquetados representa una solución de mayor
> calidad. Esta comparación es independiente de la optimalidad alcanzada
> dentro de cada formulación, dado que los modelos considerados pueden
> definir espacios de soluciones diferentes.

### Evitar esta redacción

No afirmar automáticamente:

> Model1 obtuvo una solución subóptima.

si Model1 resolvió su propia formulación a optimalidad.

Es preferible escribir:

> Model1 alcanzó el óptimo de su formulación restringida con 6 ítems,
> mientras que Model5, al contemplar configuraciones adicionales, obtuvo
> un empaquetado de 7 ítems para la misma instancia geométrica.

------------------------------------------------------------------------

## 22. Calidad respecto del mejor resultado observado

Para una instancia, puede construirse conceptualmente una referencia de
mejor calidad observada.

Ejemplo:

  Instancia     Model1   Model5   Andrade   Mejor observado
  ----------- -------- -------- --------- -----------------
  caso7              6        7         7                 7
  caso8             15       16        14                16
  caso9             12       12        13                13

Para un problema de maximización:

``` text
mejor observado(caso7) = 7
mejor observado(caso8) = 16
mejor observado(caso9) = 13
```

Esto permite analizar cuánto se aleja cada enfoque del mejor packing
observado.

Ejemplo para `caso7`:

``` text
(7 - 6) / 7 = 0.142857...
```

El resultado de 6 contiene aproximadamente un 14,29 % menos de ítems que
el mejor valor observado de 7.

**No confundir "mejor valor observado" con "óptimo global demostrado"**,
salvo que exista una referencia externa o una demostración de
optimalidad para el problema de referencia.

------------------------------------------------------------------------

## 23. ¿Qué páginas mirar primero?

Orden recomendado al analizar un experimento real:

### 1. `stat_Status.html`

Verificar que los modelos hayan terminado correctamente.

Pregunta:

> ¿La comparación incluye ejecuciones válidas y comparables?

### 2. `solvedata.html`

Inspeccionar valores concretos por instancia.

Preguntas:

> ¿Qué valor objetivo obtuvo cada modelo?

> ¿Qué tiempos registró?

> ¿Dónde aparecen diferencias?

### 3. `stat_SolutionQuality.html`

Analizar la calidad de los empaquetados obtenidos.

Pregunta:

> ¿Qué enfoque logra empaquetar más ítems para las mismas instancias
> geométricas?

### 4. `stat_Efficiency.html`

Analizar el costo computacional.

Preguntas:

> ¿Qué modelo es más rápido?

> ¿Qué tan lejos se encuentra del mejor tiempo observado?

> ¿El comportamiento es consistente?

### 5. Performance Profiles

Utilizarlos cuando exista un conjunto suficientemente grande de
instancias.

Pregunta:

> ¿Con qué frecuencia cada enfoque se mantiene cerca del mejor
> rendimiento observado?

------------------------------------------------------------------------

## 24. Qué NO concluir con solamente dos instancias

La prueba inicial utiliza:

``` text
caso2
caso4
```

El objetivo de esta prueba es **validar el pipeline y aprender a leer
PAVER**.

No corresponde concluir, a partir de dos casos, que:

-   un modelo es generalmente más rápido;
-   un modelo escala mejor;
-   un enfoque produce mejores soluciones en general;
-   un modelo es más robusto;
-   una media representa el comportamiento global.

Con dos instancias:

-   las medias son descriptivas de esos dos casos;
-   los boxplots tienen poco valor;
-   los perfiles de rendimiento tienen muy pocos puntos;
-   `better`, `close` y `worse` pueden cambiar completamente al agregar
    nuevas instancias.

La interpretación científica debe realizarse sobre el conjunto
definitivo de benchmarks.

------------------------------------------------------------------------

## 25. Sobre `BacktrackingMonoitemExacto`

El backtracking exacto puede ser útil como algoritmo de referencia y
para validar resultados.

Sin embargo, debe tenerse en cuenta que es un enfoque especializado para
el problema mono-item.

En instancias pequeñas puede resultar extremadamente rápido y
convertirse frecuentemente en el `virt.best` de tiempo.

Esto puede dominar los gráficos relativos de eficiencia.

### No eliminarlo automáticamente

Su inclusión o exclusión depende de la pregunta experimental.

Si la pregunta es:

> ¿Cómo se comportan todos los enfoques implementados para el problema
> mono-item?

puede incluirse.

Si la pregunta es específicamente:

> ¿Cómo se compara el modelo propuesto con otros modelos de programación
> matemática?

puede ser conveniente:

-   presentar una comparativa principal entre los modelos relevantes;
-   utilizar el backtracking como referencia exacta o validación;
-   o generar análisis adicionales con y sin el backtracking.

La decisión debe documentarse. No conviene excluir un algoritmo
solamente porque "gana" los gráficos.

------------------------------------------------------------------------

## 26. Diseño recomendado del experimento final

El conjunto definitivo debería seguir estas reglas:

1.  Todos los modelos se ejecutan sobre las mismas instancias
    geométricas.
2.  Los nombres de instancia son idénticos entre modelos.
3.  El criterio de medición temporal es el mismo.
4.  El límite de tiempo es el mismo.
5.  Se registra una ejecución por combinación `instancia + modelo`,
    salvo diseño explícito con repeticiones.
6.  Los estados de terminación se registran de forma coherente.
7.  El sentido de optimización se mantiene consistente.
8.  Se documentan las diferencias entre los espacios de soluciones de
    cada modelo.
9.  La calidad se interpreta mediante el valor objetivo obtenido para la
    instancia geométrica.
10. No se confunde el mejor valor observado con un óptimo global
    conocido.

### Ejemplo esperado

``` text
* Trace Record Definition
* InputFileName,SolverName,ModelStatus,SolverStatus,ObjectiveValue,SolverTime
caso7,Model5Orchestrator,1,1,7,2.51
caso7,Model1,1,1,6,0.32
caso7,AndradeBirginBigM,1,1,7,1.10
caso7,BacktrackingMonoitemExacto,1,1,7,0.08
caso8,Model5Orchestrator,1,1,16,4.22
caso8,Model1,1,1,14,0.91
caso8,AndradeBirginBigM,1,1,16,2.80
caso8,BacktrackingMonoitemExacto,1,1,16,0.15
```

Los números anteriores son solamente ilustrativos.

------------------------------------------------------------------------

## 27. Comando de referencia rápida

Desde:

``` text
I:\Mi unidad\Tesina\Paver
```

ejecutar:

``` cmd
py -3.6 src\paver\paver.py "I:\Mi unidad\Tesina\output.trc" --mintime 0.001 --failtime 900 --writehtml "I:\Mi unidad\Tesina\resultados\paver_casos_2_4"
```

Abrir:

``` cmd
start "" "I:\Mi unidad\Tesina\resultados\paver_casos_2_4\index.html"
```

### Validar PAVER

``` cmd
py -3.6 src\paver\paver.py --help
```

------------------------------------------------------------------------

## 28. Checklist para dentro de cinco meses

Si se retoma PAVER después de mucho tiempo:

-   [ ] Ir a `I:\Mi unidad\Tesina\Paver`.
-   [ ] Recordar que PAVER se ejecuta con `py -3.6`.
-   [ ] Validar con `py -3.6 src\paver\paver.py --help`.
-   [ ] Revisar que `CASE_NAME` coincida con la instancia ejecutada.
-   [ ] Limpiar o regenerar el `.trc`.
-   [ ] Confirmar una fila por `instancia + modelo`.
-   [ ] Confirmar que todos los modelos usen las mismas instancias.
-   [ ] Revisar cómo se mide `SolverTime`.
-   [ ] Evitar tiempos cero o utilizar `--mintime 0.001`.
-   [ ] Hacer coincidir `--failtime` con el límite temporal
    experimental.
-   [ ] Ejecutar PAVER.
-   [ ] Abrir `index.html`.
-   [ ] Revisar primero `Status`.
-   [ ] Revisar `solvedata`.
-   [ ] Analizar `Solution Quality`.
-   [ ] Analizar `Efficiency`.
-   [ ] Interpretar performance profiles solamente con un conjunto
    razonable de instancias.
-   [ ] Recordar: los enfoques comparados pueden tener espacios de
    soluciones diferentes.
-   [ ] No confundir "óptimo de una formulación restringida" con "mejor
    packing observado".
-   [ ] No confundir `virt.best` con un modelo real.
-   [ ] No confundir "mejor observado" con "óptimo global demostrado".

------------------------------------------------------------------------

## 29. Idea central para recordar

PAVER no entiende la matemática específica del 2DBPP.

PAVER ve:

``` text
instancia
modelo/enfoque
estado
valor objetivo
tiempo
```

La interpretación científica la define la tesina.

En este trabajo:

``` text
Efficiency
-> costo computacional de cada enfoque

Solution Quality
-> cantidad de ítems empaquetados para una misma instancia geométrica
```

Un modelo puede ser óptimo dentro de su propia formulación y, aun así,
producir un packing con menor cantidad de ítems que otro enfoque cuyo
espacio de soluciones es más amplio.

Esa diferencia no invalida la comparación: **es parte de lo que se desea
estudiar**.

------------------------------------------------------------------------

## 30. Estado actual

Al momento de escribir este documento:

-   PAVER está localizado y funcionando.
-   Se confirmó que debe ejecutarse con Python 3.6.
-   Se generó correctamente un informe HTML.
-   Se realizó una prueba con `caso2` y `caso4`.
-   Se compararon:
    -   `Model5Orchestrator`
    -   `Model1`
    -   `AndradeBirginBigM`
    -   `BacktrackingMonoitemExacto`
-   Se utiliza temporalmente:
    -   `--mintime 0.001`
    -   `--failtime 900`
-   La prueba de dos instancias tiene fines de validación y aprendizaje.
-   El siguiente paso es adaptar la configuración para ejecutar
    sistemáticamente el conjunto definitivo de instancias y generar el
    `.trc` completo.
