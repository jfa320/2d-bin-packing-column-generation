import cplex
from cplex.exceptions import CplexSolverError
from trace_file_generator import TraceFileGenerator


from Objects import Slice
from Objects import Item

from position_generator import *

NOMBRE_MODELO="Model4Maestro"

model_status="1"
solver_status="1"
objective_value=0
solver_time=1

# Constantes del problema

# Caso 5: 

# ITEMS_QUANTITY = 6  # constante N del modelo
# ITEMS = list(range(1, ITEMS_QUANTITY + 1)) 
# BIN_WIDTH = 6  # W en el modelo
# slice_height = 3  # H en el modelo

# ITEM_WIDTH = 3  # w en el modelo
# ITEM_HEIGHT = 2  # h en el modelo


CASE_NAME="inst2"

BIN_WIDTH = 6 # W en el modelo
BIN_HEIGHT=4
ITEM_WIDTH= 2 # w en el modelo
ITEM_HEIGHT= 3 # h en el modelo

slices=[] #TODO CARGAR ARRAY CON LO DEL ESCLAVO
slice_height = [] # H_r en el modelo #TODO CARGAR ARRAY
SET_POS_Y= generate_master_model_positions(BIN_HEIGHT)
ITEMS_QUANTITY= 10 
ITEMS = list(range(1, ITEMS_QUANTITY + 1)) # constante I del modelo

slices_quantity=len(slices)

REL_POS_ITEM_Y=[] #TODO PENSAR COMO CARGARLO, QUIZAS CON EL NUMERO DE ITEM Y SU POSICION
ITEM_HEIGHTS=[] #TODO CARGAR ARRAY CON LO QUE VENGA DEL ESCLAVO


EXECUTION_TIME=2 # in seconds

def create_and_solve_master_model(manual_interruption, max_time, initial_slice):
    #valores por default para enviar a paver
    model_status="1"
    solver_status="1"
    objective_value=0
    solver_time=1
    slices.append(initial_slice)
    slices_quantity=len(slices)
    
    try:
        # Crear el modelo CPLEX
        model = cplex.Cplex()
        
        initial_time=model.get_time()

        model.set_problem_type(cplex.Cplex.problem_type.LP)
        model.objective.set_sense(model.objective.sense.maximize)

        # Definir el limite tiempo de la ejecución en un minuto
        model.parameters.timelimit.set(max_time)

        # Variables para indicar si uso o no la slice r en el bin (para la FO)
        # Acá defino la FUNCION OBJETIVO
        p_r_names  = [f"p_{r}" for r in range(slices_quantity)]
        coeffs = [1.0] * slices_quantity
        model.variables.add(names=p_r_names, obj=coeffs, lb=[0.0] * slices_quantity, ub=[1.0] * slices_quantity, types="C" * slices_quantity) #Relajo la variable binaria a continua para buscar solucion dual


        # Variables para indicar si la slice r ocupa la posición p (s_{rp})
        s_rp_names = [f"s_{r},{p}" for r in range(slices_quantity) for p in SET_POS_Y]
        s_rp_coeffs = [0.0]* (len(slices) * len(SET_POS_Y)) 
        model.variables.add(names=s_rp_names, obj=s_rp_coeffs, lb=[0.0] * len(s_rp_names), ub=[1.0] * len(s_rp_names), types="C" * len(s_rp_names)) #Relajo la variable binaria a continua para buscar solucion dual

        # Variables para indicar la ubicacion y donde se ubica una slice r
        y_r_names = [f"y_{r}" for r in range(slices_quantity)]
        model.variables.add(names=y_r_names, obj=[0.0] * len(y_r_names), types="C" * len(y_r_names), lb=[0.0] * len(y_r_names))

        # Variables para determinar si una slice i se ubica arriba de otra slice j
        z_ij_names = [f"z_{i},{j}" for i in range(slices_quantity) for j in range(slices_quantity) if i != j]
        model.variables.add(names=z_ij_names, obj=[0.0] * len(z_ij_names), lb=[0.0] * len(z_ij_names), ub=[1.0] * len(z_ij_names), types="C" * len(z_ij_names)) #Relajo la variable binaria a continua para buscar solucion dual

        # Variables w_{i,r} (indica si el ítem i está en la slice r)
        w_ir_names = [f"w_{i},{r}" for i in ITEMS for r in range(slices_quantity)]
        model.variables.add(names=w_ir_names, obj=[0.0] * len(w_ir_names), lb=[0.0] * len(w_ir_names), ub=[1.0] * len(w_ir_names), types="C" * len(w_ir_names)) #Relajo la variable binaria a continua para buscar solucion dual
     
        # Variables y_{i,r} indica la posicion absoluta en el eje y del item i de la slice r en el bin
        y_ir_names = [f"y_{i},{r}" for i in ITEMS for r in range(slices_quantity)]
        model.variables.add(names=y_ir_names, obj=[0.0] * len(y_ir_names), types="C" * len(y_ir_names), lb=[0.0] * len(y_ir_names))

        
        # Restricción (1): Cada ítem se ubica solo en una slice
        for i in ITEMS:
            var_w_ir = [f"w_{i},{r}" for r in range(slices_quantity)]
            model.linear_constraints.add(
                lin_expr=[cplex.SparsePair(ind=var_w_ir, val=[1] * len(var_w_ir))],
                senses=["L"], rhs=[1]
            )
        
        # Restricción (2): Un ítem pertenece a una slice solo si la slice es seleccionada
        for i in ITEMS:
            for r in range(slices_quantity):
                model.linear_constraints.add(
                    lin_expr=[cplex.SparsePair(ind=[f"w_{i},{r}", f"p_{r}"], val=[1, -1])],
                    senses=["L"], rhs=[0]
                )

        # Restricción (3): La suma de las alturas de las slices seleccionadas no excede la altura del bin
        model.linear_constraints.add(
            lin_expr=[cplex.SparsePair(ind=p_r_names, val=[slice_height[r] for r in range(slices_quantity)])],
            senses=["L"], rhs=[BIN_HEIGHT]
        )

        # Restricción (4): Si se elige una slice, debe ocupar una sola posición en el bin
        for r in range(slices_quantity):
            var_s_rp = [f"s_{r},{p}" for p in SET_POS_Y]
            model.linear_constraints.add(
                lin_expr=[cplex.SparsePair(ind=var_s_rp + [f"p_{r}"], val=[1] * len(var_s_rp) + [-1])],
                senses=["L"], rhs=[0]
            )

        # Restricciones (5) y (6): Las slices no deben solaparse verticalmente
        for r in range(slices_quantity):
            for rp in range(slices_quantity):
                if r != rp:
                    model.linear_constraints.add(
                        lin_expr=[cplex.SparsePair(ind=[f"y_{r}", f"y_{rp}", f"z_{rp},{r}"], val=[1, -1, BIN_HEIGHT])],
                        senses=["L"], rhs=[BIN_HEIGHT] - slice_height[r]
                    )
                    model.linear_constraints.add(
                        lin_expr=[cplex.SparsePair(ind=[f"y_{rp}", f"y_{r}", f"z_{r},{rp}"], val=[1, -1, BIN_HEIGHT])],
                        senses=["L"], rhs=[BIN_HEIGHT] - slice_height[rp]
                    )

        # Restricción (7): Cada par de slices deben estar en una relación de arriba o abajo, no ambas
        for r in range(slices_quantity):
            for rp in range(slices_quantity):
                if r != rp:
                    model.linear_constraints.add(
                        lin_expr=[cplex.SparsePair(ind=[f"z_{r},{rp}", f"z_{rp},{r}"], val=[1, 1])],
                        senses=["E"], rhs=[1]
                    )

        # Restricción (8): Establece la posicion absoluta en el bin de cada item de una slice
        for i in ITEMS:
            for r in range(slices_quantity):
                model.linear_constraints.add(
                    lin_expr=[cplex.SparsePair(ind=[f"y_{i},{r}", f"y_{r}"], val=[1, -1])],
                    senses=["E"], rhs=[REL_POS_ITEM_Y[i,r]] #TODO REVISAR COMO ACCEDER A ESTE ARRAY (quizas usar diccionarios)
                )

        # Restricción (9) y (10): Asegura que los items de las slices no se solapen entre sí
        for i in ITEMS:
            for j in ITEMS:
                if i != j:  # Solo si i y j son distintos
                    for r in range(slices_quantity):
                        for r_prime in range(slices_quantity):
                            if r != r_prime:  # Solo si r y r' son distintos
                                
                                # Restricción (9): y_{ir} + h_i <= y_{jr'} + H * z_{r,r'}
                                constraint_9 = cplex.SparsePair(
                                    ind=[f"y_{i},{r}", f"y_{j},{r_prime}", f"z_{r},{r_prime}"],
                                    val=[1.0, -1.0, -BIN_HEIGHT]
                                )
                                model.linear_constraints.add(
                                    lin_expr=[constraint_9],
                                    senses=["L"],  
                                    rhs=[-ITEM_HEIGHTS[i]]  #TODO: VER SI ACCEDO ASI AL ALTO
                                )
                                
                                # Restricción (10): y_{jr'} + h_j <= y_{ir} + H * (1 - z_{r,r'})
                                # Esto es equivalente a y_{jr'} + h_j <= y_{ir} + H - H * z_{r,r'}
                                cons10 = cplex.SparsePair(
                                    ind=[f"y_{j},{r_prime}", f"y_{i},{r}", f"z_{r},{r_prime}"],
                                    val=[1.0, -1.0, BIN_HEIGHT]
                                )
                                model.linear_constraints.add(
                                    lin_expr=[cons10],
                                    senses=["L"],  
                                    rhs=[BIN_HEIGHT - ITEM_HEIGHTS[j]]  #TODO: VER SI ACCEDO ASI AL ALTO
                                )
        
        # Desactivar la interrupción manual aquí
        manual_interruption.value = False

        # Resolver el modelo
        model.solve()

        # Obtener resultados
        solution_values = model.solution.get_values()
        objective_value = model.solution.get_objective_value()
        dual_values = model.solution.get_dual_values() #aca obtengo solucion dual
        
        print("Optimal value:", objective_value)
        for var_name, value in zip(p_r_names, solution_values):
            print(f"{var_name} = {value}")
            
        dual_solution = {}
        
        for i, dual in enumerate(dual_values):
            print(f"Constraint_ {i}: Dual Value = {dual}")
            dual_solution[f"Constraint_{i}"] = dual
        
        status = model.solution.get_status()
        final_time = model.get_time()
        solver_time=final_time-initial_time
        solver_time=round(solver_time, 2)
        
        if status == 105:  # CPLEX código 105 = Time limit exceeded
            print("The solver stopped because it reached the time limit.")
            model_status="2" #valor en paver para marcar un optimo local

        return dual_solution

    except CplexSolverError as e:
        if e.args[2] == 1217:  # Codigo de error para "No solution exists"
            print("\nNo solutions for the given model.")
            model_status="14" #valor en paver para marcar que el modelo no devolvio respuesta por error
            solver_status="4" #el solver finalizo la ejecucion del modelo
        else:
            print("CPLEX Solver Error:", e)
            model_status="12" #valor en paver para marcar un error desconocido
            solver_status="10" #el solver tuvo un error en la ejecucion


