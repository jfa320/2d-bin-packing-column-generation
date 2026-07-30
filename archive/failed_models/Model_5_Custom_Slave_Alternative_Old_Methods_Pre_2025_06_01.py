import cplex
from cplex.exceptions import CplexSolverError
from Utils.model_functions import *
from Config import *
from Objects import Slice
from Objects import Item

MODEL_NAME="Model5SlaveAlternative"


def build_items_2025_05_28(variable_names, variable_values, item_height, item_width):
    items = []
    filtered_var_names = [element for element in variable_names if element.startswith('z') or element.startswith('s')]
    filtered_values= variable_values[:len(filtered_var_names)]
    
    z_dict = {}
    s_dict = {}

    for i, element in enumerate(filtered_var_names):
        if element.startswith('z'):
            z_dict[element] = filtered_values[i]
        elif element.startswith('s'):
            s_dict[element] = filtered_values[i]
    
    for name, value in z_dict.items():
        if value > 0.5:  # Considerar solo las variables activas (a veces toma el 0.999 como un 1)
            parts = name.split("_")
            id_value = int(parts[1])  
            rotated = True if s_dict.get("s_"+str(id_value)) > 0.5 else False
            item_to_add=Item(height=item_height, width=item_width, rotated=rotated,id=id_value+1)
            if(not item_to_add in items):
                items.append(item_to_add)
    return items

def build_items_old(variable_names, variable_values, item_height, item_width):
    items = []
    print("CONSTRUIR ITEMS")
    print("variable_names: ",variable_names)
    print("variable_values: ",variable_values)
    for name, value in zip(variable_names, variable_values):
        if value > 0.5:  # Considerar solo las variables activas (a veces toma el 0.999 como un 1)
            parts = name.split("_")
            item_type, id_value = parts[0], int(parts[1])  # Obtener item_type (`onX` o `onY`) y el índice del ítem
            
            rotated = True if item_type == "onY" else False
            item_to_add=Item(height=item_height, width=item_width, rotated=rotated,id=id_value)
            if(not item_to_add in items):
                items.append(item_to_add)
            
    return items


def build_occupied_positions_2025_05_28(variable_names, variable_values):
    occupied_positions = []
    position_dict =dict([(letra, numero) for letra, numero in zip(variable_names, variable_values) if letra.startswith('x') or letra.startswith('y')])
    
    print("posiciones aca: ",position_dict)
    
    for name, value in position_dict.items():
        if 'x' in name:  
            x_value=position_dict[name]
            id_value=name.split("_")[1]
            y_value=position_dict["y_"+id_value]
            occupied_positions.append((x_value, y_value))
            
    print("posiciones ocupadas: ",occupied_positions)
    return occupied_positions
    

def build_occupied_positions_old(variable_names, variable_values):
    occupied_positions = []
       
    for name, value in zip(variable_names, variable_values):
        if value > 0.5:  # Considerar solo variables activas
            parts = name.split("_")  # Dividir el nombre de la variable
            x, y = int(parts[2]), int(parts[3])  # Extraer x e y
            occupied_positions.append((x, y))  # Agregar a la lista
    return occupied_positions

def get_max_y(occupied_positions,item_height,item_width):
    #TODO: Revisar si este metodo es necesario
    if not occupied_positions:
        return None  # Manejar caso donde la lista esté vacía
    final_height=max(y for _, y in occupied_positions) + max(item_height,item_width)
    return final_height

def create_slave_model_old(max_time, XY_x, XY_y, items, dual_values):    
    print("--------------------------------------------------------------------------------------------------------------------")
    print("IN - Create Slave Model")
    XY = set(XY_x).union(set(XY_y)) 
    I = items  # Lista de ítems disponibles
    P_star=dual_values
    
    print("P_star: ",P_star)
    
    try:
        # Crear el modelo
        model = cplex.Cplex()

        model.set_problem_type(cplex.Cplex.problem_type.LP)

        model.parameters.timelimit.set(max_time)
        initial_time=model.get_time()
        added_constraints = set()
        
        # Configurar como un problema de maximización
        model.objective.set_sense(model.objective.sense.maximize)

        # Función objetivo
        # variable_names = []
        # obj_coeffs = []
        # print("aca: "+str(P_star))
        # print("aca: "+str(I))      
        # for i in I:
        #     for (x, y) in XY_x:
        #         var_name = f"onX_{i}_{x}_{y}"
        #         variable_names.append(var_name)
        #         obj_coeffs.append(P_star[i.get_id()-1])
        #     for (x, y) in XY_y:
        #         var_name = f"onY_{i}_{x}_{y}"
        #         variable_names.append(var_name)
        #         obj_coeffs.append(P_star[i.get_id()-1])
        
        # Función objetivo
        variable_names = []
        obj_coeffs = []

        # Crear las variables para ítems acostados
        for i in I:
            for (x, y) in XY_x:
                var_name = f"onX_{i.get_id()}_{x}_{y}"
                variable_names.append(var_name)
                
                # Coeficiente de la variable en la función objetivo
                pi_i = P_star["pi"].get(i.get_id(), 0)
                lambda_xy = P_star["lambda"].get((x, y), 0)
                coeff = pi_i - lambda_xy
                obj_coeffs.append(coeff)

        # Crear las variables para ítems parados
        for i in I:
            for (x, y) in XY_y:
                var_name = f"onY_{i.get_id()}_{x}_{y}"
                variable_names.append(var_name)
                
                # Coeficiente de la variable en la función objetivo
                pi_i = P_star["pi"].get(i.get_id(), 0)
                mu_xy = P_star["mu"].get((x, y), 0)
                coeff = pi_i - mu_xy
                obj_coeffs.append(coeff)

        print("variable_names: ",variable_names)
        print("obj_coeffs: ",obj_coeffs)
        
        add_variables(model,variable_names,obj_coeffs,"B")

        # Restricción 1: No solapamiento de ítems
        for (x, y) in XY:
            coeficientes = {}  # Diccionario para consolidar coeficientes de las variables

            for i in I:
                if (x, y) in XY_x:  # Si la posición está en XY_x
                    var_name = f"onX_{i.get_id()}_{x}_{y}"
                    coeficientes[var_name] = coeficientes.get(var_name, 0) + 1

                if (x, y) in XY_y:  # Si la posición está en XY_y
                    var_name = f"onY_{i.get_id()}_{x}_{y}"
                    coeficientes[var_name] = coeficientes.get(var_name, 0) + 1

            # Crear listas de variables y coeficientes consolidados
            vars = list(coeficientes.keys())
            coefficients = list(coeficientes.values())
            # Agregar restricción al modelo
            add_constraint_set(model, coefficients, vars, rhs=1, sense="L", added_constraints=added_constraints)


        # Restricción 2: Un ítem no puede estar acostado y parado al mismo tiempo
        for i in I:
            coeficientes = {}  # Diccionario para consolidar coeficientes de las variables

            for (x, y) in XY_x:  # Posiciones en XY_x
                var_name = f"onX_{i.get_id()}_{x}_{y}"
                coeficientes[var_name] = coeficientes.get(var_name, 0) + 1

            for (x, y) in XY_y:  # Posiciones en XY_y
                var_name = f"onY_{i.get_id()}_{x}_{y}"
                coeficientes[var_name] = coeficientes.get(var_name, 0) + 1

            # Crear listas de variables y coeficientes consolidados
            vars = list(coeficientes.keys())
            coefficients = list(coeficientes.values())

            # Agregar restricción al modelo
            add_constraint_set(model, coefficients, vars, rhs=1, sense="L", added_constraints=added_constraints)

        print("OUT - Create Slave Model")    
        return model
    except CplexSolverError as e:
        raise
        
    

def create_slave_model_2025_05_28(max_time, XY_x, XY_y, items, dual_values, slice_height, bin_width,non_rotated_item_height,non_rotated_item_width):    
    print("--------------------------------------------------------------------------------------------------------------------")
    print("IN - Create Slave Model")
    I = items  # Lista de ítems disponibles
    A_i=dual_values
    h = non_rotated_item_height
    w = non_rotated_item_width
    H_r= slice_height
    W= bin_width
    M= max(H_r, W) #maximo entre la altura de la slice y el ancho del bin
    print(f"H_r: {H_r}, W: {W}, h: {h}, w: {w}, M: {M}")
    print("A_i: ",A_i)
    print("ITEMS: ",I)
    
    try:
        # Crear el modelo
        model = cplex.Cplex()

        model.set_problem_type(cplex.Cplex.problem_type.LP)

        model.parameters.timelimit.set(max_time)
        initial_time=model.get_time()
        added_constraints = set()
        
        # Configurar como un problema de maximización
        model.objective.set_sense(model.objective.sense.maximize)

        # Función objetivo
        z_i_names = []
        x_i_names = []
        y_i_names = []
        s_i_names = []
        l_ij_names=[]
        d_ij_names=[]
        
        obj_coeffs = []

        # Crear las variables para indicar si incluyo item en la slice (z_i)
        for i in I:
            var_name = f"z_{i.get_id()-1}" 
            z_i_names.append(var_name)
            # Coeficiente de la variable en la función objetivo
            A_i_valor = A_i["pi"].get(i.get_id()-1, 0) #TODO MODIFICAR ACA PARA QUE TOME LA POSICION DE PI
            coeff = A_i_valor
            obj_coeffs.append(coeff)
            
        add_variables(model,z_i_names,obj_coeffs,"B")
        
        obj_coeffs.clear()
        # Crear variables para determinar si el item está rotated (s_i)
        for i in I:
            var_name = f"s_{i.get_id()-1}"
            s_i_names.append(var_name)
            coeff = 0
            obj_coeffs.append(coeff)
        add_variables(model,s_i_names,obj_coeffs,"B")
            
        # Crear variables para determinar si el item i está a la izquierda de j (l_ij)
        obj_coeffs.clear()
        for i in I:
            for j in I:
                if i.get_id()-1 < j.get_id()-1:
                    var_name = f"l_{i.get_id()-1}_{j.get_id()-1}"
                    l_ij_names.append(var_name)
                    coeff = 0
                    obj_coeffs.append(coeff)
        add_variables(model,l_ij_names,obj_coeffs,"B")
        
        obj_coeffs.clear()
        # Crear variables para determinar si el item i está debajo de j (d_ij)
        for i in I:
            for j in I:
                if i.get_id()-1 < j.get_id()-1:
                    var_name = f"d_{i.get_id()-1}_{j.get_id()-1}"
                    d_ij_names.append(var_name)
                    coeff = 0
                    obj_coeffs.append(coeff)            
        
        add_variables(model,d_ij_names,obj_coeffs,"B")
          
        obj_coeffs.clear()
        # Crear las variables para posicion sobre eje x del item i (x_i)
        for i in I:
            var_name = f"x_{i.get_id()-1}"
            x_i_names.append(var_name)
            # Coeficiente de la variable en la función objetivo
            coeff = 0
            obj_coeffs.append(coeff)
            
        add_variables(model,x_i_names,obj_coeffs,"I")
        
        obj_coeffs.clear()
        # Crear las variables para posicion sobre eje Y del item i (Y_i)
        for i in I:
            var_name = f"y_{i.get_id()-1}"
            y_i_names.append(var_name)
            # Coeficiente de la variable en la función objetivo
            coeff = 0
            obj_coeffs.append(coeff)

        add_variables(model,y_i_names,obj_coeffs,"I")
        
        obj_coeffs.clear()
        
        

        # Restricción 1: Relacion item y rotacion
        for i in I:
            indexes = [s_i_names[i.get_id()-1],z_i_names[i.get_id()-1]]
            coeffs = [1,-1]
            constraint_rhs=0
            constraint_sense="L"
            add_constraint_set(model,coeffs,indexes,constraint_rhs,constraint_sense,added_constraints,f"consItemRotado_{i.get_id()-1}")
        
        # Restricción 2: No exceder limite a lo ancho de la slice
        for i in I:
            indexes = [x_i_names[i.get_id()-1],s_i_names[i.get_id()-1]]
            coeffs = [1,h-w]
            constraint_rhs=W-w
            constraint_sense="L"
            add_constraint_set(model,coeffs,indexes,constraint_rhs,constraint_sense,added_constraints,f"consLimiteAncho_{i.get_id()-1}")
        
       
        # Restricciones (4-5-6) para evitar superposicion entre items
        for i in I:
            for j in I:
                if i.get_id() < j.get_id():
                    id_i = i.get_id() - 1
                    id_j = j.get_id() - 1
                    
                    # x_i + w(1 - s_i) + h s_i <= x_j + M(1 - l_ij)
                    indexes = [x_i_names[id_i], s_i_names[id_i], x_i_names[id_j], f"l_{id_i}_{id_j}"]
                    coeffs = [1, h - w, -1, M]
                    constraint_rhs = M - w
                    add_constraint_set(model, coeffs, indexes, constraint_rhs, "L", added_constraints, f"consSuperposicionX_{id_i}_{id_j}")

                    # y_i + h(1 - s_i) + w s_i <= y_j + M(1 - d_ij)
                    indexes = [y_i_names[id_i], s_i_names[id_i], y_i_names[id_j], f"d_{id_i}_{id_j}"]
                    coeffs = [1, w - h, -1, M]
                    constraint_rhs = M - h
                    add_constraint_set(model, coeffs, indexes, constraint_rhs, "L", added_constraints, f"consSuperposicionY_{id_i}_{id_j}")

                    # l_ij + d_ij >= z_i + z_j - 1
                    indexes = [f"l_{id_i}_{id_j}", f"d_{id_i}_{id_j}", z_i_names[id_i], z_i_names[id_j]]
                    coeffs = [1, 1, -1, -1]
                    constraint_rhs = -1
                    add_constraint_set(model, coeffs, indexes, constraint_rhs, "G", added_constraints, f"consDisyuncion_{id_i}_{id_j}")
                    
        # Restricción 7: Que el inicio del item quede dentro de la slice
        for i in I:
            indexes = [y_i_names[i.get_id()-1]]
            coeffs = [1]
            constraint_rhs=H_r
            constraint_sense="L"
            add_constraint_set(model,coeffs,indexes,constraint_rhs,constraint_sense,added_constraints,f"consItemDentroBin_{i.get_id()-1}")
            
        print("OUT - Create Slave Model")    
        return model
    except CplexSolverError as e:
        raise


def create_slave_model_old_2(max_time, XY_x, XY_y, items, dual_values, slice_height, bin_width,non_rotated_item_height,non_rotated_item_width):    
    print("--------------------------------------------------------------------------------------------------------------------")
    print("IN - Create Slave Model")
    I = items  # Lista de ítems disponibles
    A_i=dual_values
    h = non_rotated_item_height
    w = non_rotated_item_width
    H_r= slice_height
    W= bin_width
    M= max(H_r, W) #maximo entre la altura de la slice y el ancho del bin
    print(f"H_r: {H_r}, W: {W}, h: {h}, w: {w}, M: {M}")
    print("A_i: ",A_i)
    try:
        # Crear el modelo
        model = cplex.Cplex()

        model.set_problem_type(cplex.Cplex.problem_type.LP)

        model.parameters.timelimit.set(max_time)
        initial_time=model.get_time()
        added_constraints = set()
        
        # Configurar como un problema de maximización
        model.objective.set_sense(model.objective.sense.maximize)

        # Función objetivo
        z_i_names = []
        x_i_names = []
        y_i_names = []
        s_i_names = []
        l_ij_names=[]
        d_ij_names=[]
        
        obj_coeffs = []

        # Crear las variables para indicar si incluyo item en la slice (z_i)
        for i in I:
            var_name = f"z_{i.get_id()-1}"
            z_i_names.append(var_name)
            # Coeficiente de la variable en la función objetivo
            A_i_valor = A_i["pi"].get(i.get_id()-1, 0)
            coeff = A_i_valor
            obj_coeffs.append(coeff)
            
        add_variables(model,z_i_names,obj_coeffs,"B")
        
        obj_coeffs.clear()
        # Crear variables para determinar si el item está rotated (s_i)
        for i in I:
            var_name = f"s_{i.get_id()-1}"
            s_i_names.append(var_name)
            coeff = 0
            obj_coeffs.append(coeff)
        add_variables(model,s_i_names,obj_coeffs,"B")
            
        # Crear variables para determinar si el item i está a la izquierda de j (l_ij)
        obj_coeffs.clear()
        for i in I:
            for j in I:
                if i.get_id()-1 < j.get_id()-1:
                    var_name = f"l_{i.get_id()-1}_{j.get_id()-1}"
                    l_ij_names.append(var_name)
                    coeff = 0
                    obj_coeffs.append(coeff)
        add_variables(model,l_ij_names,obj_coeffs,"B")
        
        obj_coeffs.clear()
        # Crear variables para determinar si el item i está debajo de j (d_ij)
        for i in I:
            for j in I:
                if i.get_id()-1 < j.get_id()-1:
                    var_name = f"d_{i.get_id()-1}_{j.get_id()-1}"
                    d_ij_names.append(var_name)
                    coeff = 0
                    obj_coeffs.append(coeff)            
        
        add_variables(model,d_ij_names,obj_coeffs,"B")
          
        obj_coeffs.clear()
        # Crear las variables para posicion sobre eje x del item i (x_i)
        for i in I:
            var_name = f"x_{i.get_id()-1}"
            x_i_names.append(var_name)
            # Coeficiente de la variable en la función objetivo
            coeff = 0
            obj_coeffs.append(coeff)
            
        add_variables(model,x_i_names,obj_coeffs,"I")
        
        obj_coeffs.clear()
        # Crear las variables para posicion sobre eje Y del item i (Y_i)
        for i in I:
            var_name = f"y_{i.get_id()-1}"
            y_i_names.append(var_name)
            # Coeficiente de la variable en la función objetivo
            coeff = 0
            obj_coeffs.append(coeff)

        add_variables(model,y_i_names,obj_coeffs,"I")
        
        obj_coeffs.clear()
        
        

        # Restricción 1: Relacion item y rotacion
        for i in I:
            indexes = [s_i_names[i.get_id()-1],z_i_names[i.get_id()-1]]
            coeffs = [1,-1]
            constraint_rhs=0
            constraint_sense="L"
            add_constraint_set(model,coeffs,indexes,constraint_rhs,constraint_sense,added_constraints,f"consItemRotado_{i.get_id()-1}")
        
        # Restricción 2: No exceder limite a lo ancho de la slice
        for i in I:
            indexes = [x_i_names[i.get_id()-1],s_i_names[i.get_id()-1]]
            coeffs = [1,h-w]
            constraint_rhs=W-w
            constraint_sense="L"
            add_constraint_set(model,coeffs,indexes,constraint_rhs,constraint_sense,added_constraints,f"consLimiteAncho_{i.get_id()-1}")
        
        # Restricción 3: No exceder limite a lo alto de la slice
        for i in I:
            indexes = [y_i_names[i.get_id()-1],s_i_names[i.get_id()-1]]
            coeffs = [1,w-h]
            constraint_rhs=H_r-h
            constraint_sense="L"
            add_constraint_set(model,coeffs,indexes,constraint_rhs,constraint_sense,added_constraints,f"consLimiteAlto_{i.get_id()-1}")
        # Restricciones (4-5-6) para evitar superposicion entre items
        for i in I:
            for j in I:
                if i.get_id() < j.get_id():
                    id_i = i.get_id() - 1
                    id_j = j.get_id() - 1
                    
                    # x_i + w(1 - s_i) + h s_i <= x_j + M(1 - l_ij)
                    indexes = [x_i_names[id_i], s_i_names[id_i], x_i_names[id_j], f"l_{id_i}_{id_j}"]
                    coeffs = [1, h - w, -1, M]
                    constraint_rhs = M - w
                    add_constraint_set(model, coeffs, indexes, constraint_rhs, "L", added_constraints, f"consSuperposicionX_{id_i}_{id_j}")

                    # y_i + h(1 - s_i) + w s_i <= y_j + M(1 - d_ij)
                    indexes = [y_i_names[id_i], s_i_names[id_i], y_i_names[id_j], f"d_{id_i}_{id_j}"]
                    coeffs = [1, w - h, -1, M]
                    constraint_rhs = M - h
                    add_constraint_set(model, coeffs, indexes, constraint_rhs, "L", added_constraints, f"consSuperposicionY_{id_i}_{id_j}")

                    # l_ij + d_ij >= z_i + z_j - 1
                    indexes = [f"l_{id_i}_{id_j}", f"d_{id_i}_{id_j}", z_i_names[id_i], z_i_names[id_j]]
                    coeffs = [1, 1, -1, -1]
                    constraint_rhs = -1
                    add_constraint_set(model, coeffs, indexes, constraint_rhs, "G", added_constraints, f"consDisyuncion_{id_i}_{id_j}")
        print("OUT - Create Slave Model")    
        return model
    except CplexSolverError as e:
        raise


def solve_slave_model(model, queue, manual_interruption, bin_width, item_height, item_width):
    print("IN - Solve Slave Model")
    #valores por default para enviar a paver
    model_status, solver_status, objective_value, solver_time = "1", "1", 0, 1
    try:
        # Desactivar la interrupción manual aquí
        initial_time = model.get_time()
        manual_interruption.value = False
        print("Voy a resolver el esclavo")
        # Resolver el modelo
        model.solve()
        objective_value = model.solution.get_objective_value()

        # Imprimir resultados
        print("Optimal value:", objective_value)
        #imprimo valor que toman las variables
        for _, var_name in enumerate(model.variables.get_names()):
            print(f"{var_name} = {model.solution.get_values(var_name)}")
            
        # Obtener la función objetivo y sus coeficientes
        obj_coefs = model.objective.get_linear()  # Obtiene los coeficientes
        var_names = model.variables.get_names()   # Obtiene los nombres de las variables

        # Imprimir la función objetivo en formato legible
        objetivo_str = " + ".join([f"{coef}*{var}" for coef, var in zip(obj_coefs, var_names)])
        print(f"Función Objetivo: {objetivo_str}")
        
        

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
        variable_names = model.variables.get_names()
        variable_values = model.solution.get_values()
        items=build_items_2025_05_28(variable_names, variable_values, item_height, item_width)
        
        occupied_positions=build_occupied_positions_2025_05_28(variable_names, variable_values)
        height= get_max_y(occupied_positions,item_height,item_width)
        
        print("Valor objetivo del esclavo", objective_value)
        # if objective_value <= 0:
        EPSILON = 1e-5
        if objective_value  <= EPSILON:
            print("El valor objetivo del esclavo es insignificante. Fin del proceso.")
            return None
        print("OUT - Solve Slave Model")
        
        slice_height = height or 1
        found_slice = Slice(
            height=slice_height,
            width=bin_width,
            items=items,
            item_start_points=occupied_positions,
        )
        return found_slice
    except CplexSolverError as e:
        print("Error al resolver el modelo esclavo:", e)
        handle_solver_error(e, queue,solver_time)

