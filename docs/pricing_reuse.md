# Reutilización del pricing

La reutilización forma parte del algoritmo base del modelo propio. Las llamadas
existentes a `orchestrator()` y `execute_with_time_limit()` utilizan
`pricing_mode="auto"`, sin cambiar el CLI ni el contrato de resultados.

## Selección del modo

| Modo | Algoritmo base | Mejoras prácticas activas |
|---|---|---|
| `auto` (predeterminado) | Reutilizar | Reconstruir |
| `reuse` | Reutilizar | Error explícito |
| `rebuild` | Reconstruir | Reconstruir |

Se considera el valor efectivo de `finalization_heuristics`: un `False`
explícito selecciona el flujo base aunque el flag global sea `True`. Cuando
se omite ese argumento, se usa `USE_PRACTICAL_CG_ENHANCEMENTS`. La selección
del modo se hace una vez por ejecución y se transmite por el argumento
`pricing_mode` al proceso hijo.

El modo automático mantiene disponible el recorrido de las mejoras opcionales,
que agrega exclusiones y modifica el objetivo en una segunda fase. Reutilizar
ese recorrido requeriría restaurar sus restricciones temporales y su objetivo;
esa extensión no está incluida.

## Modelo persistente

`IncrementalPricingModel`, en `models/column_generation/slave_problem.py`,
pertenece a una sola instancia normalizada. En su primera llamada utiliza el
constructor existente y guarda las claves de las celdas de cada variable de
colocación. Las siguientes llamadas actualizan el objetivo sobre el mismo
objeto CPLEX:

```text
coeficiente(z) = 1 - suma(pi de las celdas ocupadas por z)
```

Se reemplazan todos los coeficientes, incluidos los que pasan a cero. Las
variables auxiliares de ventana mantienen coeficiente cero. Las posiciones,
variables, límites y restricciones geométricas permanecen iguales para una
misma instancia. `create_slave_model()` sigue disponible para construir un
modelo independiente y `solve_slave_model()` conserva su interfaz.

La estructura persiste, pero cada solve inicia una búsqueda MIP nueva con
`parameters.advance=0`. El prototipo conservaba la información de búsqueda
de CPLEX. Durante la integración, eso cambió los desempates de columnas en
`case7` (bin 50×20, ítem 13×8): obtuvo LP 7 e IP restringido 6, mientras la
referencia reconstruida obtuvo 7/7. Al desactivar el inicio avanzado, la
reutilización volvió a obtener 7/7. La opción está documentada en el
[manual de CPLEX 22.1.1](https://www.ibm.com/docs/en/icos/22.1.1?topic=parameters-advanced-start-switch).
Este ajuste conserva el ahorro de construcción; no garantiza una trayectoria
idéntica para cualquier instancia o versión de CPLEX.

Si falla una actualización, el objeto posiblemente modificado parcialmente
se cierra y se reconstruye con la geometría completa y los duales actuales.
También se reconstruye si cambia la cantidad de variables o restricciones.
La recuperación queda registrada en stdout. La sesión se libera antes de
construir el master entero final y al salir por errores.

`pricing_build_time_s` incluye la primera construcción y las actualizaciones
siguientes; `pricing_solve_time_s` conserva los bloques puros de resolución.
El cierre normal de la sesión queda dentro del tiempo de CG. Se conservan
los snapshots, las evidencias de convergencia y los formatos de reportes.

## Forzar la reconstrucción

La opción sigue disponible para regresiones y comparaciones. Ejemplo para un
script Python en Windows:

```python
from config import get_instance
from models.column_generation.column_generation_solver import execute_with_time_limit

if __name__ == "__main__":
    result = execute_with_time_limit(
        60, instance=get_instance("case7"),
        finalization_heuristics=False, pricing_mode="rebuild",
    )
    print(result.execution)
```

Para el funcionamiento habitual se omite `pricing_mode`: el flujo base usa
reutilización automáticamente. La instancia continúa propagándose mediante
`ConfigData` y los argumentos del proceso hijo.

## Evidencia de los experimentos previos a la integración

Los ensayos se realizaron con Python 3.10.4 y CPLEX 22.1.1.0. La referencia
intacta y la versión experimental partieron del commit
`97559b60cf4e82618109689f05caab2c4d4bc63c`. Sus worktrees `pricing-reference`
y `pricing-reuse`, incluidos los resultados crudos en `Results/`, se conservaron
sin modificar al integrar el cambio en el checkout principal.

| Caso | Comparación | Total referencia (s) | Total reutilización (s) | Reducción |
|---|---|---:|---:|---:|
| IB_004 | Medianas de tres mediciones, presupuesto 60 s | 11,354663 | 6,764635 | 40,4 % |
| case18 | Medianas de tres mediciones, presupuesto 60 s | 22,902837 | 20,200175 | 11,8 % |
| IB_006 | Una medición, presupuesto 1200 s | 344,739835 | 275,027628 | 20,2 % |

En estos casos coincidieron los valores LP/IP y la evidencia de convergencia
comparados. IB_006 conservó un entero restringido de 29, inferior a la
referencia del catálogo de 30. En IB_009, con 1200 s por variante, se completaron
16 pricings en referencia y 23 con reutilización, sin IP final reportado.
IIB_005 no terminó su primer pricing; IIIB_001 completó dos en cada variante.
Los tiempos limitados no se interpretan como tiempos de convergencia ni
permiten calcular un speedup de terminación.

Estos resultados respaldan reducir el armado repetido, pero la trayectoria
puede cambiar por empates. El solve acumulado puede aumentar, y el ahorro
total depende de la instancia y del número de llamadas. El master entero
restringido no certifica optimalidad global del packing.

El informe experimental detallado y las auditorías permanecen en
`docs/pricing_reuse_large_cases.md` y en los archivos
`Results/pricing_reuse_*20261025*` del worktree `pricing-reuse`. Describen la
versión medida antes de que `auto` pasara a ser el valor predeterminado.
El prototipo también conservaba los inicios avanzados. Por eso los porcentajes
históricos no se atribuyen directamente a la integración con `advance=0`.

## Pruebas de integración

Las pruebas específicas comprueban equivalencia de estructura, coeficientes,
óptimos y cotas con modelos recién construidos; secuencias de duales que vuelven
al valor inicial; coeficientes cero; reconstrucción después de un fallo
parcial; cierre de recursos; geometría normalizada y transporte mediante spawn.

Además se verifica que una llamada base sin seleccionar un modo crea una sola
sesión real y reutiliza el mismo objeto, que `auto` respeta la configuración
efectiva de heurísticas y que sigue disponible la reconstrucción explícita.
La instrumentación anterior se contrasta por separado con su modo `rebuild`.

La selección de pruebas de integración y regresión terminó con **403 pruebas
aprobadas**. Incluye `case7` con llamada directa y mediante spawn, en modo
automático y explícito, y la verificación de factibilidad de su solución.
La prueba existente de `case2` sigue esperando 4 ítems y obtiene 3: se reprodujo
también en el checkout de referencia intacto y con búsqueda nueva en pricing.
Ese fallo previo permanece registrado; no se alteró su expectativa para
aprobarla ni se considera resuelto por este cambio.

Se realizó además una comparación breve de la versión integrada: una ejecución
por combinación, sin calentamientos, procesos separados, presupuesto de 60 s
y guarda externa de 75 s. Las cuatro ejecuciones finalizaron normalmente,
con evidencia de convergencia LP por la cota del pricing. También coincidieron
las iteraciones: 71 en IB_004 y 212 en case18.

| Caso | LP/IP en ambos modos | Total `rebuild` (s) | Total `auto` (s) | Preparación `rebuild` (s) | Preparación `auto` (s) |
|---|---:|---:|---:|---:|---:|
| IB_004 | 20/20 | 12,602 | 9,745 | 3,391 | 0,195 |
| case18 | 50/50 | 44,941 | 26,591 | 12,786 | 0,379 |

Los resultados y hashes de los dos módulos se guardaron en
[Results/pricing_reuse_integration_20261025.json](../Results/pricing_reuse_integration_20261025.json).
Es una comprobación de integración, con una sola medición por variante;
no acredita estabilidad estadística ni extiende los resultados históricos de
20 minutos a la política nueva de búsqueda. El entero sigue siendo restringido
al pool generado y no certifica optimalidad global por sí solo.
