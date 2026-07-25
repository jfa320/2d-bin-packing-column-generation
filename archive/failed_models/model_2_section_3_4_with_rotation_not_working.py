import cplex
from cplex.exceptions import CplexError

# Parámetros


# NOT WORKING
n_items = 6  # Número de items
W = 6  # Ancho del bin
H = 4  # Alto del bin

w = 2   # Ancho de los items
h = 3   # Altura de los items

# NOT WORKING
# H = 5  # Alto del bin
# W = 6  # Ancho del bin
# n_items = 6  # Número de items
# h = 4   # Altura de los items
# w = 3   # Ancho de los items



# WORKING
# H = 6  # Alto del bin
# W = 6  # Ancho del bin
# n_items = 6  # Número de items
# h = 3   # Altura de los items
# w = 2   # Ancho de los items

Q_X_i = len([x for x in range(W) if x <= W - w])
Q_Y_i = len([y for y in range(H) if y <= H - h])
Q_X_i_prime = len([x for x in range(W) if x <= W - h])
Q_Y_i_prime = len([y for y in range(H) if y <= H - w])

# Crear el modelo
model = cplex.Cplex()
model.set_log_stream(None)
model.set_results_stream(None)
model.set_warning_stream(None)
model.set_error_stream(None)

# Definir las variables
m_vars = []  # Variables m_i y m_{i'}
n_vars = []  # Variables n_{i,x,y} y n_{i',x,y}
r_vars = []  # Variables r_{x,y}
nprime=[]
# Variables m_i y m_{i'}
for i in range(n_items):
    m_vars.append(f"m_{i}")
    m_vars.append(f"m_{i}'")

# Variables n_{i,x,y} y n_{i',x,y}, y r_{x,y}
for i in range(n_items):
    for x in range(W):
        for y in range(H):
            if x <= W - w and y <= H - h:  # Espacio para la versión no rotada
                n_vars.append(f"n_{i}_{x}_{y}")
            if x <= W - h and y <= H - w:  # Espacio para la versión rotada
                n_vars.append(f"n_{i}'_{x}_{y}")
for x in range(W):
    for y in range(H):
        r_vars.append(f"r_{x}_{y}")

# Añadir las variables al modelo
model.variables.add(names=m_vars, types=['B'] * len(m_vars))
model.variables.add(names=n_vars, types=['B'] * len(n_vars))
model.variables.add(names=r_vars, types=['B'] * len(r_vars))

# Función objetivo: maximizar la suma de m_i + m_{i'}
objective = [(m_vars[i], 1) for i in range(len(m_vars))]
model.objective.set_sense(model.objective.sense.maximize)
model.objective.set_linear(objective)

# Restricción 1: r_{x,y} = ...
for x in range(W):
    for y in range(H):
        row = []
        val = []
        for i in range(n_items):
            if x <= W - w and y <= H - h:
                for x_prime in range(max(0, x - w + 1), x + 1):
                    for y_prime in range(max(0, y - h + 1), y + 1):
                        row.append(f"n_{i}_{x_prime}_{y_prime}")
                        val.append(1)
            if x <= W - h and y <= H - w:
                for x_prime in range(max(0, x - h + 1), x + 1):
                    for y_prime in range(max(0, y - w + 1), y + 1):
                        row.append(f"n_{i}'_{x_prime}_{y_prime}")
                        val.append(1)
        row.append(f"r_{x}_{y}")
        val.append(-1)
        model.linear_constraints.add(
            lin_expr=[cplex.SparsePair(ind=row, val=val)],
            senses=["E"],
            rhs=[0]
        )

# Restricción 2: m_i + m_{i'} <= suma de n_{i,x,y} + n_{i',x,y}
for i in range(n_items):
    row = [f"m_{i}", f"m_{i}'"]
    val = [1, 1]
    for x in range(W):
        for y in range(H):
            if x <= W - w and y <= H - h:
                row.append(f"n_{i}_{x}_{y}")
                val.append(-1)
            if x <= W - h and y <= H - w:
                row.append(f"n_{i}'_{x}_{y}")
                val.append(-1)
    model.linear_constraints.add(
        lin_expr=[cplex.SparsePair(ind=row, val=val)],
        senses=["L"],
        rhs=[0]
    )

# Restricción 3: suma de n_{i,x,y} + n_{i',x,y} <= Q(X_i)Q(Y_i)m_i + Q(X_{i'})Q(Y_{i'})m_{i'}


for i in range(n_items):
    row = []
    val = []
    for x in range(W):
        for y in range(H):
            if x <= W - w and y <= H - h:
                row.append(f"n_{i}_{x}_{y}")
                val.append(1)
            if x <= W - h and y <= H - w:
                row.append(f"n_{i}'_{x}_{y}")
                val.append(1)
    row.append(f"m_{i}")
    val.append(-Q_X_i * Q_Y_i)
    row.append(f"m_{i}'")
    val.append(-Q_X_i_prime * Q_Y_i_prime)
    model.linear_constraints.add(
        lin_expr=[cplex.SparsePair(ind=row, val=val)],
        senses=["L"],
        rhs=[0]
    )

# Restricción 4: m_i + m_{i'} <= 1
for i in range(n_items):
    row = [f"m_{i}", f"m_{i}'"]
    val = [1, 1]
    model.linear_constraints.add(
        lin_expr=[cplex.SparsePair(ind=row, val=val)],
        senses=["L"],
        rhs=[1]
    )

# Resolver el modelo
try:
    model.solve()
except CplexError as exc:
    print(exc)

# # Imprimir resultados
# print("Objective value:", model.solution.get_objective_value())
# for i in range(n_items):
#     normal_var = f"m_{i}"
#     rotated_var = f"m_{i}'"
#     print(f"Item {i} placed: Normal - {model.solution.get_values(normal_var)}, Rotated - {model.solution.get_values(rotated_var)}")

#        # Imprimir las posiciones en las que se coloca cada item
#     if model.solution.get_values(normal_var) > 0.5:
#         print(f"Item {i} is placed in its normal orientation at:")
#         for x in range(W):
#             for y in range(H):
#                 var_name = f"n_{i}_{x}_{y}"
#                 if model.solution.get_values(var_name) > 0.5:
#                     print(f"  Position (x={x}, y={y})")
#     elif model.solution.get_values(rotated_var) > 0.5:
#         print(f"Item {i} is placed in its rotated orientation at:")
#         for x in range(W):
#             for y in range(H):
#                 if x <= W - h and y <= H - w:
#                     var_name = f"n_{i}'_{x}_{y}"
#                     if model.solution.get_values(var_name) > 0.5:
#                         print(f"  Position (x={x}, y={y})")

# Imprimir resultados
print("Objective value:", model.solution.get_objective_value())

for i in range(n_items):
    normal_var = f"m_{i}"
    rotated_var = f"m_{i}'"
    print(f"Item {i} placed: Normal - {model.solution.get_values(normal_var)}, Rotated - {model.solution.get_values(rotated_var)}")

    # Imprimir las posiciones en las que se coloca cada item
    if model.solution.get_values(normal_var) > 0.5:
        print(f"Item {i} is placed in its normal orientation at:")
        found_position = False  # Variable para verificar si se encontró al menos una posición
        for x in range(W):
            for y in range(H):
                if x <= W - w and y <= H - h:
                    var_name = f"n_{i}_{x}_{y}"
                    if model.solution.get_values(var_name) > 0.5:
                        print(f"  Position (x={x}, y={y})")
                        found_position = True
        if not found_position:
            print(f"  No valid position found for Item {i}, check model constraints or logic.")


    elif model.solution.get_values(rotated_var) > 0.5:
        print(f"Item {i} is placed in its rotated orientation at:")
        found_position = False  # Variable para verificar si se encontró al menos una posición
        for x in range(W):
            for y in range(H):
                if x <= W - h and y <= H - w:
                    var_name = f"n_{i}'_{x}_{y}"
                    if model.solution.get_values(var_name) > 0.5:
                        print(f"  Position (x={x}, y={y})")
                        found_position = True
        if not found_position:
            print(f"  No valid position found for Item {i}, check model constraints or logic.")

