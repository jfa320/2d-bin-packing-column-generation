# Algoritmo

## Flujo general del algoritmo

El enfoque implementado utiliza un esquema de generación de columnas compuesto por un modelo maestro y un modelo esclavo, también denominado problema de *pricing*.

El modelo maestro selecciona las rebanadas que forman la solución, mientras que el modelo esclavo genera nuevas rebanadas a partir de los valores duales obtenidos al resolver la relajación lineal del maestro.

```mermaid
flowchart TD
    A[Definir la instancia] --> B[Generar posiciones válidas]
    B --> C[Generar rebanadas iniciales]
    C --> D[Inicializar el modelo maestro]
    D --> E[Resolver el modelo maestro relajado]
    E --> F[Obtener los valores duales]
    F --> G[Resolver el modelo esclavo<br/>o problema de pricing]

    G --> H{¿Se encontró una rebanada<br/>mejorante?}

    H -- Sí --> I{¿La rebanada ya existe?}

    I -- No --> J[Agregar la rebanada<br/>como nueva columna del maestro]
    J --> E

    I -- Sí --> K[Agregar un no-good cut<br/>al modelo esclavo]
    K --> G

    H -- No --> L[Finalizar la generación de columnas]
    L --> M[Resolver el modelo maestro entero]
    M --> N[Obtener la solución final]
```

El proceso comienza con la definición de la instancia, la generación de las posiciones válidas y la construcción de un conjunto inicial de rebanadas.

A continuación, se resuelve la relajación lineal del modelo maestro y se obtienen sus valores duales. Estos valores son utilizados por el modelo esclavo o problema de *pricing* para buscar una nueva rebanada mejorante.

Si la rebanada encontrada todavía no forma parte del maestro, se incorpora como una nueva columna y se vuelve a resolver el modelo maestro relajado.

Si la rebanada ya había sido generada, se agrega un *no-good cut* al modelo esclavo para excluir esa solución y buscar una rebanada alternativa.

Cuando el modelo esclavo no encuentra nuevas rebanadas mejorantes, finaliza la generación de columnas. Finalmente, se resuelve el modelo maestro entero utilizando las columnas generadas y se obtiene la solución final.

## Condiciones de corte:

1. Si el modelo esclavo no genera una rebanada válida, se detiene el proceso.
2. Si el modelo esclavo devuelve una rebanada ya generada previamente, la rebanada no se agrega. En su lugar, se agrega una restricción de exclusión (no-good cut) para excluir esa solución del esclavo y se intenta buscar una alternativa durante un número acotado de iteraciones. Si no se encuentra una alternativa nueva mejorante, se detiene la generación.
3. Si el costo reducido es cercano a cero, se permite una fase adicional de exploración para buscar rebanadas alternativas. Esta fase está acotada por un máximo de M iteraciones.
4. Si el modelo maestro no mejora luego de N iteraciones, se detiene el proceso por posible estancamiento.
5. El proceso iterativo continúa resolviendo el modelo maestro relajado y el modelo esclavo hasta que se cumple alguna condición de corte.
6. Finalmente, se resuelve el modelo maestro en su versión entera con todas las rebanadas generadas para obtener la solución final.

---
## En cada iteración:

1. Se resuelve el modelo maestro relajado
2. Se obtienen duales
3. Se resuelve el modelo esclavo con esos duales
4. Se obtiene una nueva rebanada
5. Se decide si agregarla al maestro o finalizar el proceso en base a las condiciones de corte

---

## Rol de cada modelo

### Maestro

- selecciona rebanadas que maximizan la cantidad items
- asegura que no haya colisiones entre los items de las rebanadas elegidas


### Esclavo

- genera nuevas rebanadas que potencialmente mejoran la solución actual
- determina la ubicación de los ítems dentro del bin
- Nota: puede devolver una rebanada ya generada en casos de degeneración o empates; en ese caso la implementación la descarta y fuerza la búsqueda de una alternativa

---

## Definición de rebanada
Una rebanada es un espacio dentro del bin que se extiende de un extremo al otro de su ancho, de forma análoga a un corte guillotina horizontal, donde se ubica un conjunto de ítems. Cada ítem posee una posición `(x, y)` correspondiente a la esquina inferior izquierda desde donde es ubicado.

La rebanada tiene asociados un ancho `W` (igual al ancho del bin) y un alto `hr`. Sin embargo, los ítems que la componen pueden exceder hacia arriba dicho alto, por lo que el contorno ocupado por la rebanada no necesariamente coincide con un rectángulo de dimensiones `W x hr`. 

Como condición de pertenencia, la esquina inferior izquierda de cada ítem debe ubicarse dentro de la región de ancho `W` y alto `hr - ε`, donde ε es un valor positivo pequeño utilizado para evitar que un ítem quede exactamente sobre el borde superior de la rebanada.

### Representación interna

Cada rebanada almacena:

- `id`: identificador único.
- `ancho`: ancho de la rebanada.
- `alto`: alto de la rebanada.
- `items`: lista de ítems contenidos en la rebanada.
- `puntosDeInicioItems`: lista de posiciones `(x, y)` correspondientes a los puntos de inicio de los ítems.

### Relación con los ítems

Cada ítem contenido en una rebanada posee una posición `(x, y)` expresada en el sistema de coordenadas del bin. Esta posición corresponde a la esquina inferior izquierda del ítem y no es relativa a la rebanada.

La rebanada no posee una posición propia, sino que queda completamente determinada por las posiciones absolutas de los ítems que la componen dentro del bin. En consecuencia, dos rebanadas con la misma disposición relativa de ítems, pero ubicadas a distinta altura, se consideran rebanadas distintas.

---

## Rebanadas repetidas

Una rebanada se considera repetida si coincide con una rebanada ya generada previamente según la posición y orientación de sus ítems.

La implementación construye una firma de cada rebanada a partir de las tuplas `(x, y, rotado)` de sus ítems. Si la firma de una rebanada candidata ya pertenece al conjunto de firmas generadas, la rebanada no se agrega al maestro.

Desde el punto de vista de generación de columnas, una columna ya presente en el maestro no aporta una mejora nueva. Sin embargo, debido a degeneración, empates o tolerancias numéricas, el esclavo puede volver a devolver una rebanada conocida.

---

## No-good cuts

Un no-good cut es una restricción agregada al modelo esclavo para impedir que vuelva a devolver exactamente la misma solución.

Si una solución del esclavo activa las variables `z_1, z_2, ..., z_k`, se agrega la restricción `z_1 + z_2 + ... + z_k <= k - 1`.

De esta forma, al menos una de esas variables debe cambiar en la siguiente solución. En la implementación, esto se usa para excluir rebanadas repetidas o soluciones ya exploradas durante la fase de búsqueda adicional.

---

## Condiciones de finalización

- el esclavo no genera una rebanada válida
- no se encuentra una rebanada nueva con costo reducido positivo
- se detectan rebanadas repetidas y no se logra obtener una alternativa nueva luego de aplicar no-good cuts
- el maestro se estanca luego de varias iteraciones sin mejora significativa
- se alcanza el límite de intentos adicionales o de tiempo

---
## Detalles importantes:

- el modelo maestro no posiciona rebanadas ni items. Simplemente elige las rebanadas cuyos items no colisionan entre sí
- en línea a lo anterior, la rebanada viene armada desde el esclavo con sus items y con ellos su ubicación en el bin

---

## Diagnóstico del caso `50 x 20`, item `13 x 8`

### Caso observado

Para el caso:

- bin: `50 x 20`
- item: `13 x 8`
- rotación permitida: `8 x 13`

el algoritmo obtiene una solución entera de `6` ítems, usando dos rebanadas iniciales homogéneas:

- una rebanada inferior con 3 ítems no rotados
- una rebanada superior con 3 ítems no rotados

Geométricamente existe una solución de `7` ítems si se reemplaza la rebanada inferior por una rebanada mixta:

- 3 ítems no rotados en `(0,0)`, `(13,0)`, `(26,0)`
- 1 ítem rotado en `(39,0)`
- más la rebanada superior de 3 ítems no rotados

La rebanada mixta esperada es:

```text
[(0,0,NR), (13,0,NR), (26,0,NR), (39,0,R)]
```

### Verificaciones realizadas

Se verificó que la rebanada mixta no está bloqueada por restricciones geométricas del esclavo:

- las variables correspondientes existen en el pricing
- la combinación es factible si se fuerza en el modelo esclavo
- no hay un no-good cut que la elimine
- al inicio tiene costo reducido positivo

Con los duales iniciales del maestro relajado se observó:

```text
rebanada base de 3 NR: valor pricing = 0
item rotado adicional en x = 39: coeficiente marginal = +1
rebanada mixta completa: valor pricing = +1
```

Por lo tanto, el cuarto ítem no tiene coeficiente negativo. La rebanada mixta domina a la rebanada de 3 desde el punto de vista del pricing.

Sin embargo, la rebanada mixta no domina a todas las columnas posibles. El pricing encuentra antes muchas columnas con mayor valor reducido, especialmente columnas de 5 ítems o columnas de 4 ítems con otra geometría. Por eso la columna deseada no aparece en el pool.

### Rebanadas de 4 ítems

El pricing sí puede generar rebanadas de 4 ítems y también puede generar rebanadas mixtas. El problema no es la cardinalidad ni la mezcla de orientaciones.

Lo que no aparece es la rebanada de 4 específica que es compatible con la rebanada superior y permite construir la solución entera de `7`.

Esto indica que el problema no es:

```text
"el pricing no genera mixtas"
```

sino:

```text
"el pricing no rankea suficientemente alto la columna mixta útil para el entero"
```

### Efecto del corte por estancamiento

Se probó aumentar el corte por estancamiento para permitir más iteraciones de generación de columnas. Con más iteraciones:

- se generan más columnas
- aparecen columnas de 4 ítems
- el maestro relajado llega a valor `7`
- el maestro entero final sigue en `6`

Esto muestra que el pool generado alcanza para construir una solución fraccional de valor `7`, pero no contiene una combinación entera compatible de valor `7`.

Cuando el maestro relajado llega a `7`, la rebanada mixta esperada ya tiene costo reducido `0`, por lo que el pricing estándar deja de tener incentivo para generarla.

### Degeneración dual observada

El hallazgo más importante es que los duales del maestro por celdas son altamente degenerados.

En la primera iteración del caso analizado, los duales no nulos se concentraron en solo dos celdas:

```text
dual(0,0) = 3
dual(0,8) = 3
resto de las celdas = 0
```

Esto ocurre porque el maestro impone restricciones de no colisión por celda:

```text
para cada celda (x,y):
sum rebanadas que ocupan (x,y) <= 1
```

Una rebanada ocupa muchas celdas, pero una solución dual extrema puede concentrar todo el precio de esa rebanada en una sola celda. Matemáticamente puede ser válido para la relajación, pero produce una señal pobre para el pricing.

Con esos duales, el pricing interpreta:

```text
evitar la celda (0,0) es muy valioso
el resto de las celdas no tiene costo
```

Esto penaliza columnas geométricamente útiles que tocan esa celda, como la rebanada mixta esperada, y favorece columnas desplazadas o con otra geometría que evitan la celda cara pero no necesariamente ayudan a la solución entera.

### Interpretación

El maestro actual cumple dos funciones:

- selecciona rebanadas para maximizar la cantidad de ítems
- asegura que no haya colisiones entre ítems de distintas rebanadas mediante restricciones por celda

Esta formulación es geométricamente válida como un set packing por celdas, pero puede no estar bien alineada con generación de columnas. Los duales asociados a restricciones tan locales pueden ser muy degenerados y guiar al pricing hacia columnas buenas para la relajación lineal, pero no necesariamente útiles para la solución entera.

El caso evidencia una brecha entre:

```text
columnas con buen costo reducido para el maestro relajado
```

y:

```text
columnas útiles para construir una solución entera compatible
```

### Líneas de trabajo posibles

Sin considerar el generador inicial como solución, las líneas relevantes son:

- revisar la formulación del maestro, especialmente el uso de restricciones por celda como fuente de duales
- estudiar estabilización o suavizado de duales para evitar precios extremadamente concentrados
- analizar si conviene una formulación alternativa del maestro con restricciones menos locales o con una estructura de compatibilidad diferente
- medir la degeneración dual en otros casos para confirmar si los fallos se correlacionan con duales concentrados

La conclusión actual es que el problema no parece ser que la columna faltante sea infactible o tenga costo reducido negativo. El problema parece estar en la señal dual inducida por el maestro por celdas y en cómo esa señal rankea las columnas dentro del pricing.
