import cplex
from cplex.exceptions import CplexSolverError
from Utils.model_functions import *
from Config import *

MODEL_NAME="Model5Master"



def create_master_model_old(max_time,slices,bin_height,bin_width,item_height,item_width,items,pos_xy_x,pos_xy_y):
    print("IN - Create Master Model")
    H = bin_height  # Alto del bin 
    W = bin_width  # Ancho del bin
    I = items  # Lista de ítems disponibles
    R = slices  # Lista de slices disponibles
    H_ab= {} # subconjunto de posiciones que inician en (a, b) para items en orientacion horizontal.
    for a, b in pos_xy_x:
        H_ab[(a, b)] = [(x, y) for x in range(a, a + item_width) for y in range(b, b + item_height)]
        
    V_ab= {} # subconjunto de posiciones que inician en (a, b) para items en orientacion vertical.
    for a, b in pos_xy_y:
        V_ab[(a, b)] = [(x, y) for x in range(a, a + item_height) for y in range(b, b + item_width)]
        
    R_r_xy={} # indica si la slice r con r ∈ R posee un item en la coordenada (x, y)
    
    # Recorrer cada slice en R y llenar R_r_xy
    for r_idx, slice in enumerate(R, start=0): 
        R_r_xy[r_idx] = slice.get_item_start_points()

    
    try:
        # Crear instancia del problema
        model = cplex.Cplex()
        model.set_problem_type(cplex.Cplex.problem_type.MILP) 

        model.parameters.timelimit.set(max_time)

        # Variables
        # Variables p_r (binarias)
        p_r_names = [f"p_{r.get_id()-1}" for r in R]
        model.variables.add(names=p_r_names, types=[model.variables.type.binary] * len(R))

        # Variables y_r (enteras)
        y_r_names = [f"y_{r.get_id()}" for r in R]
        model.variables.add(names=y_r_names, types=[model.variables.type.integer] * len(R))

        # Función objetivo
        coef_obj = [r.get_total_items() for r in R]  # Coeficientes de p_r en la función objetivo
    
        model.objective.set_sense(model.objective.sense.maximize)
        model.objective.set_linear(list(zip(p_r_names, coef_obj)))

        added_constraints = set()
        # Restricción 1: Un ítem no puede estar en más de una slice activa
        for i in I:
            print("Slices: ",R)
            indexes = [p_r_names[r.get_id()-1] for r in R if r.contains_item(i)]
            coeffs = [1] * len(indexes)
            constraint_rhs=1.0
            constraint_sense="L"
            add_constraint_set(model,coeffs,indexes,constraint_rhs,constraint_sense,added_constraints,f"consItem_{i.get_id()}")
        
        
        # Esta restriccion es vieja
        # Ejemplos de conjuntos:
        # H_(0,0)={(0,0),(1,0),(0,1),(1,1),(0,2),(1,2)}
        # V_(5,1)​={(5,1),(6,1)}
        # R_r_xy[1] = [(0, 0), (1, 0), (0, 1), (1, 1)] Coordenadas ocupadas en la slice 1
        # (2), (3), (4): No solapamiento
        for r in R:
            for (a, b) in R_r_xy[r.get_id()-1]:
                # Obtener posiciones horizontales y verticales
                H_ab_positions = H_ab.get((a, b), [])
                V_ab_positions = V_ab.get((a, b), [])
                
                # Restricción (2): No solapamiento horizontal
                if H_ab_positions:
                    coeff = [1 if (x, y) in R_r_xy[r.get_id()-1] else 0 for (x, y) in H_ab_positions]
                    vars = [f"p_{r.get_id()}"] * len(H_ab_positions)
                    print("COEFFS Y VARS")
                    print(coeff)
                    print(vars) 
                    add_constraint_set(model, coeff, vars, rhs=1, sense="L",added_constraints=added_constraints, constraint_name=f"consH_{a}_{b}")
                
                # Restricción (3): No solapamiento vertical
                if V_ab_positions:
                    coeff = [1 if (x, y) in R_r_xy[r.get_id()-1] else 0 for (x, y) in V_ab_positions]
                    vars = [f"p_{r.get_id()}"] * len(V_ab_positions)
                    print("COEFFS Y VARS")
                    print(coeff)
                    print(vars) 
                    add_constraint_set(model, coeff, vars, rhs=1, sense="L",added_constraints=added_constraints, constraint_name=f"consV_{a}_{b}")
                
                # Restricción (4): No solapamiento en intersección
                overlap_positions = set(H_ab_positions) & set(V_ab_positions)
                if overlap_positions:
                    coeff = [1 if (x, y) in R_r_xy[r.get_id()-1] else 0 for (x, y) in overlap_positions]
                    vars = [f"p_{r.get_id()}"] * len(overlap_positions)
                    add_constraint_set(model, coeff, vars, rhs=1, sense="L",added_constraints=added_constraints, constraint_name=f"consHV_{a}_{b}")
       
        
        # Generación del conjunto de posiciones válidas
        valid_positions = set()  # Usamos un conjunto para evitar duplicados

        # Unimos todas las posiciones de H_a,b y V_a,b para cada (a, b)
        for (a, b) in H_ab.keys():  # Iteramos sobre todas las claves de H_a,b
            valid_positions.update(H_ab[(a, b)])  # Agregamos las posiciones horizontales
        for (a, b) in V_ab.keys():  # Iteramos sobre todas las claves de V_a,b
            valid_positions.update(V_ab[(a, b)])  # Agregamos las posiciones verticales

        # Convertimos el conjunto a una lista si se necesita orden específico
        valid_positions = list(valid_positions)
        
        # Generación de la restricción en CPLEX
        # for (a, b) in valid_positions:  # Iteramos sobre las posiciones válidas
        #     coeficientes = {}  # Diccionario para consolidar coeficientes de cada p_r

        #     for r in R:  # Iteramos sobre cada slice
        #         # Verificamos posiciones en H_{a,b}
        #         for (x, y) in H_ab.get((a, b), []):  # Posiciones horizontales asociadas a (a, b)
        #             if (x, y) in R_r_xy[r.get_id() - 1]:  # Si (x, y) está ocupado por la slice r
        #                 var_name = p_r_names[r.get_id() - 1]  # Nombre de la variable p_r[r]
        #                 coeficientes[var_name] = coeficientes.get(var_name, 0) + 1  # Sumar contribución

        #         # Verificamos posiciones en V_{a,b}
        #         for (x, y) in V_ab.get((a, b), []):  # Posiciones verticales asociadas a (a, b)
        #             if (x, y) in R_r_xy[r.get_id() - 1]:  # Si (x, y) está ocupado por la slice r
        #                 var_name = p_r_names[r.get_id() - 1]  # Nombre de la variable p_r[r]
        #                 coeficientes[var_name] = coeficientes.get(var_name, 0) + 1  # Sumar contribución

        #     # Crear SparsePair consolidado
        #     restriccion = cplex.SparsePair()
        #     restriccion.ind = list(coeficientes.keys())  # Variables involucradas
        #     restriccion.val = list(coeficientes.values())  # Coeficientes consolidados
            
        #     add_constraint_set(model,  restriccion.val, restriccion.ind , rhs=1, sense="L",added_constraints=added_constraints, constraint_name=f"consColisionSlices_{a}_{b}")
        
        # Restricción para evitar colisiones de ítems entre distintas slices
        for (a, b) in valid_positions:
            # Construir la suma de términos en la restricción
            terms = []
            coefs = []

            for r in R:
                for (x, y) in H_ab.get((a, b), []):  # Asegurar que H_a_b[(a,b)] existe
                    if (x, y) in R_r_xy[r.get_id()-1]:
                        terms.append(f"p_{r.get_id()-1}")
                        coefs.append(1)

                for (x, y) in V_ab.get((a, b), []):  # Asegurar que V_a_b[(a,b)] existe
                    if (r, x, y) in R_r_xy:
                        terms.append(f"p_{r.get_id()-1}")
                        coefs.append(1)
            # Agregar la restricción al modelo: suma de términos ≤ 1
            if terms:
                add_constraint_set(model,  coefs, terms , rhs=1, sense="L",added_constraints=added_constraints, constraint_name=f"consNoSolapamiento_{a}_{b}")
        
        print("OUT - Create Master Model")
        return model
    
    except CplexSolverError as e:
        raise


def create_master_model_deprecated(max_time,slices,bin_height,bin_width,item_height,item_width,items,pos_xy_x,pos_xy_y):
    print("IN - Create Master Model")
    H = bin_height  # Alto del bin 
    R = slices  # Lista de slices disponibles
    #C_r= se puede modelar usando el metodo slice.get_total_items() - Cantidad de items en slices
    I = items  # Lista de ítems disponibles
    #A_ir = no es necesario crear un conjunto de posiciones ocupadas por slice, se puede modelar usando el metodo slice.contains_item(item)
    #H_r = no es necesario crear un conjunto de alturas ocupadas por slice, se puede modelar usando el metodo slice.get_height()
    
    try:
        # Crear instancia del problema
        model = cplex.Cplex()
        model.set_problem_type(cplex.Cplex.problem_type.MILP) 

        model.parameters.timelimit.set(max_time)

        # Variables
        # Variables p_r (binarias)
        p_r_names = [f"p_{r.get_id()}" for r in R]
        model.variables.add(names=p_r_names, types=[model.variables.type.binary] * len(R))

        # Variables y_r (enteras)
        y_r_names = [f"y_{r.get_id()}" for r in R]
        model.variables.add(names=y_r_names, types=[model.variables.type.integer] * len(R))
        
        # Variables z_{rr'} 
        z_rr_names = []
        z_rr_indices = {}
        for r1 in R:
            for r2 in R:
                if r1.get_id() != r2.get_id():
                    name = f"z_{r1.get_id()}_{r2.get_id()}"
                    z_rr_names.append(name)
                    z_rr_indices[(r1.get_id(), r2.get_id())] = name
        model.variables.add(names=z_rr_names, types=[model.variables.type.binary] * len(z_rr_names))

        print("TOTAL ITEMS POR REBANADA")
        for r in R:
            print(r.get_total_items() )

        # Función objetivo
        coef_obj = [r.get_total_items() for r in R]  # Coeficientes de p_r en la función objetivo
    
        model.objective.set_sense(model.objective.sense.maximize)
        model.objective.set_linear(list(zip(p_r_names, coef_obj)))

        added_constraints = set()
        
        # Restricción 1: Un ítem no puede estar en más de una slice activa
        for i in I:
            indexes = [p_r_names[r.get_id()-1] for r in R if r.contains_item(i)]
            coeffs = [1] * len(indexes)
            constraint_rhs=1.0
            constraint_sense="L"
            add_constraint_set(model,coeffs,indexes,constraint_rhs,constraint_sense,added_constraints,f"consItem_{i.get_id()}")
        
        # Restricción 2: no colision de slice r con r'
        for r in R:
            for r_prime in R:
                if r.get_id() != r_prime.get_id():
                    y_r = f"y_{r.get_id()}"
                    y_r_prime = f"y_{r_prime.get_id()}"
                    z_rr_prime = z_rr_indices[(r.get_id(), r_prime.get_id())]
                    coef = [1, -1 , H]
                    rhs= H - r.get_height()
                    vars=[y_r, y_r_prime, z_rr_prime]
                    add_constraint_set(model, coef, vars, rhs=rhs, sense="L", added_constraints=added_constraints,
                                     constraint_name=f"consColisionUp_{r.get_id()}_{r_prime.get_id()}")
                
        # Restricción 3: no colision de slice r' con r
        for r in R:
            for r_prime in R:
                if r.get_id() != r_prime.get_id():
                    y_r = f"y_{r.get_id()}"
                    y_r_prime = f"y_{r_prime.get_id()}"
                    z_rr_prime = z_rr_indices[(r.get_id(), r_prime.get_id())]
                    coef = [1, -1 , -H]
                    rhs= -r_prime.get_height()
                    vars=[y_r_prime, y_r, z_rr_prime]
                    add_constraint_set(model, coef, vars, rhs=rhs, sense="L", added_constraints=added_constraints,
                                     constraint_name=f"consColisionDown_{r.get_id()}_{r_prime.get_id()}")
                
        print("OUT - Create Master Model")
        return model
    
    except CplexSolverError as e:
        raise


def create_master_model_2(bin_height, bin_width, items, slices, S):
    try:
        problem = cplex.Cplex()
        problem.set_problem_type(cplex.Cplex.problem_type.LP)
        problem.objective.set_sense(problem.objective.sense.maximize)
        
        # Variables binaria p_r
        p_names = [f"p_{r.get_id()}" for r in slices]
        problem.variables.add(names=p_names, types=[problem.variables.type.binary] * len(slices))
        
        # Variables enteras y_r
        y_names = [f"y_{r.get_id()}" for r in slices]
        problem.variables.add(names=y_names, types=[problem.variables.type.integer] * len(slices), lb=[0] * len(slices))
        
        # Restricción (1): Cada ítem solo puede estar en una slice
        for i in items:
            indices = [p_names[r.get_id()-1] for r in slices if i in r.get_items()]
            problem.linear_constraints.add(
                lin_expr=[[indices, [1] * len(indices)]],
                senses=["L"],
                rhs=[1],
                names=[f"consItem_{i.get_id()}"]
            )
        
        # Restricción (2): Cada punto (a,b) solo puede estar en una slice
        for (a, b) in S:
            indices = [p_names[r.get_id()-1] for r in slices if (a, b) in r.get_item_start_points()]
            problem.linear_constraints.add(
                lin_expr=[[indices, [1] * len(indices)]],
                senses=["L"],
                rhs=[1],
                names=[f"consPoint_{a}_{b}"]
            )
        
        # Restricción (3): Suma de alturas de slices no supera bin_height
        problem.linear_constraints.add(
            lin_expr=[[p_names, [r.get_height() for r in slices]]],
            senses=["L"],
            rhs=[bin_height],
            names=["consH_Bin"]
        )
        
        # Restricción (4): Posición en y más altura no supera bin_height
        for r in slices:
            problem.linear_constraints.add(
                lin_expr=[[ [y_names[r.get_id()-1], p_names[r.get_id()-1]], [1, r.get_height()] ]],
                senses=["L"],
                rhs=[bin_height],
                names=[f"consH_{r.get_id()-1}"]
            )
        
        # Restricción (5): No solapamiento vertical entre slices
        for r in slices:
            for r2 in slices:
                if r != r2:
                    problem.linear_constraints.add(
                        lin_expr=[[ [y_names[r.get_id()-1], p_names[r.get_id()-1], y_names[r2.get_id()-1], p_names[r2.get_id()-1]], [1, bin_height, -1, bin_height] ]],
                        senses=["L"],
                        rhs=[2*bin_height-r.get_height()],
                        names=[f"consV_{r.get_id()-1}_{r2.get_id()-1}"]
                    )
        
        # Función objetivo: maximizar la cantidad de ítems en slices seleccionadas
        problem.objective.set_linear([(p_names[r.get_id()-1], r.get_total_items()) for r in slices])
        
        return problem
    
    except CplexSolverError as exc:
        print(exc)




def solve_master_model(model, queue, manual_interruption, relax_model, items, pos_xy_x, pos_xy_y):
    print("IN - Solve Master Model")
    # valores por default para enviar a paver
    model_status, solver_status, objective_value, solver_time = "1", "1", 0, 1
    
    try:    
        # Desactivar la interrupción manual aquí
        initial_time = model.get_time()
        manual_interruption.value = False
        
        
        if(relax_model):
            print("Relajando modelo...")
            model.set_problem_type(cplex.Cplex.problem_type.LP)
        else:
            print("NO RELAJO MODELO - QUEDA COMO MILP")
            model.set_problem_type(cplex.Cplex.problem_type.MILP)
        
        # Resolver el modelo
        model.solve()
            
        objective_value = model.solution.get_objective_value()
        # Imprimir resultados
        print("Optimal value:", objective_value)
        dual_values=None
        if(relax_model):
            # Obtener valores duales
            dual_values=get_dual_values(model)
            print("Dual values:", dual_values)    
            
            
        #imprimo valor que toman las variables
        for i, var_name in enumerate(model.variables.get_names()):
            print(f"{var_name} = {model.solution.get_values(var_name)}")

        status = model.solution.get_status()
        final_time = model.get_time()
        solver_time=final_time-initial_time
        solver_time=round(solver_time, 2)
        
        
        if status == 105:  # CPLEX código 105 = Time limit exceeded
            print("The solver stopped because it reached the time limit.")
            model_status="2" #valor en paver para marcar un optimo local

        # Enviar resultados a través de la cola
        queue.put({
            "model_status": model_status,
            "solver_status": solver_status,
            "objective_value": objective_value,
            "solver_time": solver_time
        })
        # Obtener la cantidad de restricciones
        
        print("OUT - Solve Master Model")
        return objective_value,dual_values
    
    except CplexSolverError as e:
        handle_solver_error(e, queue,solver_time)
  


def get_dual_values(model):
    return model.solution.get_dual_values()


def get_dual_values_old(model, I, pos_xy_x, pos_xy_y):
    
    print("Extrayendo valores duales...")
    # Inicializar diccionarios para cada componente de P_star
    P_star = {"pi": {}, "lambda": {}, "mu": {}}
    
    # Obtener los valores duales de las restricciones
    dual_values = model.solution.get_dual_values()
    print(f"todos los valores : {dual_values}")
    constraint_names=model.linear_constraints.get_names()
    # Recorrer las restricciones y mapear duales
    
    for _, (name, dual_value) in enumerate(zip(constraint_names, dual_values)):
        if name.startswith("consItem_"):
            # Restricciones relacionadas a ítems
            item_id = int(name.split("_")[1])  # Extraer el ID del ítem
            P_star["pi"][item_id] = dual_value
            print(f"Dual para ítem {item_id}: {dual_value}")
            
        elif name.startswith("consH_Bin"):
            # Restricciones relacionadas a posiciones horizontales
            # Extraer las coordenadas x, y del nombre de la restricción
            x, y = map(int, name.split("_")[1:])
            pos = (x, y)  # Crear la tupla de posición
            P_star["lambda"][pos] = dual_value
            print(f"Dual para posición horizontal {pos}: {dual_value}")
        
        elif name.startswith("consH_"):
            # Restricciones relacionadas a posiciones horizontales
            # Extraer las coordenadas x, y del nombre de la restricción
            x, y = map(int, name.split("_")[1:])
            pos = (x, y)  # Crear la tupla de posición
            P_star["lambda"][pos] = dual_value
            print(f"Dual para posición horizontal {pos}: {dual_value}")
        
        elif name.startswith("consV_"):
            # Restricciones relacionadas a posiciones verticales
            # Extraer las coordenadas x, y del nombre de la restricción
            x, y = map(int, name.split("_")[1:])
            pos = (x, y)  # Crear la tupla de posición
            P_star["mu"][pos] = dual_value
            print(f"Dual para posición vertical {pos}: {dual_value}")
            
        
    return P_star
