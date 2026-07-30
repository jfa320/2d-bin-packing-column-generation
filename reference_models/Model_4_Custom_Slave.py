import cplex
from cplex.exceptions import CplexSolverError
from trace_file_generator import TraceFileGenerator
from Objects import Slice
from Objects import Item
import multiprocessing
import time

from position_generator import *

MODEL_NAME="Model4Esclavo"

model_status="1"
solver_status="1"
objective_value=0
solver_time=1

# Constantes del problema

# Caso 5: 

# ITEMS_QUANTITY = 6  # constante N del modelo
# ITEMS = list(range(1, ITEMS_QUANTITY + 1)) 
# BIN_WIDTH = 6  # W en el modelo
# BIN_HEIGHT = 3  # H en el modelo

# ITEM_WIDTH = 3  # w en el modelo
# ITEM_HEIGHT = 2  # h en el modelo


CASE_NAME="inst2"

ITEMS_QUANTITY= 10 # constante n del modelo
ITEMS = list(range(1, ITEMS_QUANTITY + 1)) # constante I del modelo
BIN_WIDTH = 6 # W en el modelo
BIN_HEIGHT = 4 # H en el modelo

ITEM_WIDTH= 2 # w en el modelo
ITEM_HEIGHT= 3 # h en el modelo

S_star=[] #TODO Definir como le llega del maestro

# Generación de posiciones factibles para ítems y sus versiones rotadas
SET_POS_X, SET_POS_Y, SET_POS_X_I, SET_POS_Y_I = generate_positions_no_height_limit(BIN_WIDTH, BIN_HEIGHT, ITEM_WIDTH, ITEM_HEIGHT)
SET_POS_X_I_ROT = [x for x in range(BIN_WIDTH) if x <= BIN_WIDTH - ITEM_HEIGHT]
SET_POS_Y_I_ROT = [y for y in range(BIN_HEIGHT) if y <= BIN_HEIGHT]

QUANTITY_X_I = len(SET_POS_X_I)
QUANTITY_Y_I = len(SET_POS_Y_I)
QUANTITY_X_I_ROT = len(SET_POS_X_I_ROT)
QUANTITY_Y_I_ROT = len(SET_POS_Y_I_ROT)

EXECUTION_TIME=2 # in seconds

def create_and_solve_slave_model(queue, manual_interruption, max_time):
    #valores por default para enviar a paver
    model_status="1"
    solver_status="1"
    objective_value=0
    solver_time=1

    try:
        # Crear el modelo CPLEX
        model = cplex.Cplex()
        
        initial_time=model.get_time()

        model.set_problem_type(cplex.Cplex.problem_type.LP)
        model.objective.set_sense(model.objective.sense.maximize)

        # Definir el limite tiempo de la ejecución en un minuto
        model.parameters.timelimit.set(max_time)

        # Variables para indicar si el ítem o su versión rotada están en el bin (para la FO)
        var_names = [f"m_{i}" for i in ITEMS] + [f"m_rot_{i}" for i in ITEMS] 
        coeffs = [S_star[i-1] for i in ITEMS] + [S_star[i-1] for i in ITEMS] #TODO: Revisar en base a respuesta de Marcelo y ver como sacar ese dato del maestro
        model.variables.add(names=var_names, obj=coeffs, types="B" * len(var_names))


        # Variables de posición para la versión original y rotada de los ítems
        position_var_names = []
        for i in ITEMS:
            for x in SET_POS_X_I:
                for y in SET_POS_Y_I:
                    position_var_names.append(f"n_{i},{x},{y}")
            for x_rot in SET_POS_X_I_ROT:
                for y_rot in SET_POS_Y_I_ROT:
                    position_var_names.append(f"n_rot_{i},{x_rot},{y_rot}")

        position_coeffs = [0.0] * len(position_var_names)
        model.variables.add(names=position_var_names, obj=position_coeffs, types="B" * len(position_var_names))

        # Variables para las posiciones libres (r_x,y)
        r_var_names = [f"r_{x},{y}" for x in SET_POS_X for y in SET_POS_Y]
        model.variables.add(names=r_var_names, obj=[0.0] * len(r_var_names), types="B" * len(r_var_names))

        # Restricción 1: Evita solapamiento de ítems en una posición (x,y)
        for x in SET_POS_X:
            for y in SET_POS_Y:
                constraint_coeff = [1.0]  # Coeficiente de r_{x,y}
                constraint_vars = [f"r_{x},{y}"]

                for i in ITEMS:
                    for x_prime in SET_POS_X_I:
                        if x - ITEM_WIDTH + 1 <= x_prime <= x:
                            for y_prime in SET_POS_Y_I:
                                if y - ITEM_HEIGHT + 1 <= y_prime <= y:
                                    constraint_coeff.append(-1.0)
                                    constraint_vars.append(f"n_{i},{x_prime},{y_prime}")

                    for x_prime_rot in SET_POS_X_I_ROT:
                        if x - ITEM_HEIGHT + 1 <= x_prime_rot <= x:
                            for y_prime_rot in SET_POS_Y_I_ROT:
                                if y - ITEM_WIDTH + 1 <= y_prime_rot <= y:
                                    constraint_coeff.append(-1.0)
                                    constraint_vars.append(f"n_rot_{i},{x_prime_rot},{y_prime_rot}")

                model.linear_constraints.add(
                    lin_expr=[cplex.SparsePair(constraint_vars, constraint_coeff)],
                    senses=["E"], rhs=[0.0]
                )


        for i in ITEMS:
            constraint_coeff = [-1.0]  # Coeficiente para m_i
            constraint_vars = [f"m_{i}"]  # Variable m_i que indica si el ítem no rotated está en el bin

            # Sumamos todas las posiciones no rotadas posibles donde el ítem puede estar
            for x in SET_POS_X_I:
                for y in SET_POS_Y_I:
                    constraint_coeff.append(1.0)
                    constraint_vars.append(f"n_{i},{x},{y}")

            # La restricción asegura que m_i sea igual a la suma de posiciones ocupadas
            model.linear_constraints.add(
                lin_expr=[cplex.SparsePair(constraint_vars, constraint_coeff)],
                senses=["L"], rhs=[0.0]
            )

        # Restricción para ítems rotados: m_rot_i = suma de las posiciones rotadas donde está el ítem i
        for i in ITEMS:
            constraint_coeff_rot = [-1.0]  # Coeficiente para m_rot_i
            constraint_vars_rot = [f"m_rot_{i}"]  # Variable m_rot_i que indica si el ítem rotated está en el bin

            # Sumamos todas las posiciones rotadas posibles donde el ítem puede estar
            for x_rot in SET_POS_X_I_ROT:
                for y_rot in SET_POS_Y_I_ROT:
                    constraint_coeff_rot.append(1.0)
                    constraint_vars_rot.append(f"n_rot_{i},{x_rot},{y_rot}")

            # La restricción asegura que m_rot_i sea igual a la suma de posiciones ocupadas
            model.linear_constraints.add(
                lin_expr=[cplex.SparsePair(constraint_vars_rot, constraint_coeff_rot)],
                senses=["L"], rhs=[0.0]
            )

        # Restricción : suma de posiciones <= Q(X_i)*Q(Y_i) * m_i 
        for i in ITEMS:
            constraint_coeff = [-1.0]  # Coeficiente para m_i
            constraint_vars = [f"m_{i}"]

            for x in SET_POS_X_I:
                for y in SET_POS_Y_I:
                    constraint_coeff.append(1.0)
                    constraint_vars.append(f"n_{i},{x},{y}")

            model.linear_constraints.add(
                lin_expr=[cplex.SparsePair(constraint_vars, constraint_coeff)],
                senses=["L"], rhs=[QUANTITY_X_I * QUANTITY_Y_I]
            )

            constraint_coeff_rot = [-1.0]  # Coeficiente para m_rot_i
            constraint_vars_rot = [f"m_rot_{i}"]

            for x_rot in SET_POS_X_I_ROT:
                for y_rot in SET_POS_Y_I_ROT:
                    constraint_coeff_rot.append(1.0)
                    constraint_vars_rot.append(f"n_rot_{i},{x_rot},{y_rot}")

            model.linear_constraints.add(
                lin_expr=[cplex.SparsePair(constraint_vars_rot, constraint_coeff_rot)],
                senses=["L"], rhs=[QUANTITY_X_I_ROT * QUANTITY_Y_I_ROT]
            )

        # Restricción 4: m_i + m_rot_i <= 1 
        for i in ITEMS:
            model.linear_constraints.add(
                lin_expr=[cplex.SparsePair([f"m_{i}", f"m_rot_{i}"], [1.0, 1.0])],
                senses=["L"], rhs=[1.0]
            )

        # Desactivar la interrupción manual aquí
        manual_interruption.value = False

        # Resolver el model
        model.solve()

        # Obtener resultados
        solution_values = model.solution.get_values()
        objective_value = model.solution.get_objective_value()
        
        slice_items = []
        print("Optimal objective value:", objective_value)
        for var_name, value in zip(var_names, solution_values):
            print(f"{var_name} = {value}")
            if value == 1.0:
                # If the variable is active, reconstruct the selected item.
                if "n_" in var_name:  # Ítem no rotated
                    parts = var_name.replace("n_", "").split(",")
                    i = int(parts[0])
                    y = int(parts[2])
                    item = Item(
                        height=ITEM_HEIGHT,
                        width=ITEM_WIDTH,
                        rotated=False,
                        id=i,
                        position_y=y,
                    )
                    
                else:  # Ítem rotated
                    parts = var_name.replace("n_rot_", "").split(",")
                    i = int(parts[0])
                    y = int(parts[2])
                    item = Item(
                        height=ITEM_WIDTH,
                        width=ITEM_HEIGHT,
                        rotated=True,
                        id=i,
                        position_y=y,
                    )
                slice_items.append(item)

        
        status = model.solution.get_status()
        final_time = model.get_time()
        solver_time=final_time-initial_time
        solver_time=round(solver_time, 2)
        
        if status == 105:  # CPLEX código 105 = Time limit exceeded
            print("El solver se detuvo porque alcanzó el límite de tiempo.")
            model_status="2" #valor en paver para marcar un optimo local

        # Enviar resultados a través de la cola
        queue.put({
            "model_status": model_status,
            "solver_status": solver_status,
            "objective_value": objective_value,
            "solver_time": solver_time
        })
        
        slice_height = find_highest_height(slice_items) or 1
        slice = Slice(height=slice_height, width=BIN_WIDTH, items=slice_items)
        
        return slice

    except CplexSolverError as e:
        if e.args[2] == 1217:  # Codigo de error para "No solution exists"
            print("\nNo existen soluciones para el modelo dado.")
            model_status="14" #valor en paver para marcar que el modelo no devolvio respuesta por error
            solver_status="4" #el solver finalizo la ejecucion del modelo
        else:
            print("CPLEX Solver Error:", e)
            model_status="12" #valor en paver para marcar un error desconocido
            solver_status="10" #el solver tuvo un error en la ejecucion

        queue.put({
            "model_status": model_status,
            "solver_status": solver_status,
            "objective_value": objective_value,
            "solver_time": solver_time
        })


def execute_with_time_limit(max_time):
    global model_status, solver_status, objective_value, solver_time 

    # Crear una cola para recibir los resultados del subproceso
    queue = multiprocessing.Queue()

    # Crear una variable compartida para manejar la interrupción manual
    manual_interruption = multiprocessing.Value('b', True)

    # Crear el subproceso que correrá la función
    process = multiprocessing.Process(target=create_and_solve_slave_model, args=(queue, manual_interruption, max_time))

    # Iniciar el subproceso
    process.start()

    initial_time = time.time()

    # Monitorear la cola mientras el proceso está en ejecución
    while process.is_alive():

        if manual_interruption.value:
            # Si se excede el tiempo, terminamos el proceso
            if time.time() - initial_time > max_time:
                print("Tiempo límite alcanzado. Abortando el proceso.")
                model_status="14" #valor en paver para marcar que el modelo no devolvio respuesta por error
                solver_status="4" #el solver finalizo la ejecucion del modelo
                solver_time=max_time
                process.terminate()
                process.join()
                break

        time.sleep(0.1)  # Evitar consumir demasiados recursos

    # Imprimo resultados de la ejecucion que se guardan luego en el archivo trc para usar en paver
    while not queue.empty():
        message = queue.get()
        if isinstance(message, dict):
            print(message)
            model_status = message["model_status"]
            solver_status = message["solver_status"]
            objective_value = message["objective_value"]
            solver_time = message["solver_time"]



if __name__ == '__main__':
 
    execute_with_time_limit(EXECUTION_TIME)
    generator = TraceFileGenerator("output.trc")
    generator.write_trace_record(CASE_NAME, MODEL_NAME, model_status, solver_status, objective_value, solver_time)



def find_highest_height(items_list):
    highest_height=0
    for item in items_list:
        if item.get_position_y() is None:
            continue
        if item.get_position_y()+item.get_height()>highest_height:
                highest_height=item.get_position_y()+item.get_height()
    return highest_height
