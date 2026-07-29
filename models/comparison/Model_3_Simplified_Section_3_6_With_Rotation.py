import cplex
from cplex.exceptions import CplexSolverError
import multiprocessing
import time
from position_generator import generate_positions_cid_garcia, create_c_matrix
from Utils.model_functions import *
from Config import *

MODEL_NAME="Model3Pos2"

# Parámetros
W = BIN_WIDTH  # Ancho del bin
H = BIN_HEIGHT  # Alto del bin
w = ITEM_WIDTH # Ancho del item
h = ITEM_HEIGHT  # Alto del item

I = range(ITEMS_COUNT)  # Item set
# J = generate_positions2_without_rotation(W, H, w, h)  # Posiciones sin rotación
J = generate_positions_cid_garcia(W, H, w, h)  # Posiciones sin rotación

# J_rot = generate_positions2_without_rotation(W, H, h, w)  # Posiciones con rotación de 90 grados
J_rot = generate_positions_cid_garcia(W, H, h, w)  # Posiciones con rotación de 90 grados

P = [(x, y) for x in range(W) for y in range(H)]  # Puntos del bin
C = create_c_matrix(W, H, J, w, h, P)  # Matriz C para posiciones sin rotación
C_rot = create_c_matrix(W, H, J_rot, h, w, P)  # Matriz C para posiciones rotadas

# Conjunto de posiciones válidas por ítem
T = J
T_rot = J_rot
Q = len(T)  # Cantidad total de posiciones válidas por ítem
Q_rot = len(T_rot)  # Cantidad total de posiciones válidas rotadas por ítem

def create_and_solve_model(queue, manual_interruption, max_time):
    #valores por default para enviar a paver
    model_status, solver_status, objective_value, solver_time = "1", "1", 0, 1

    try:
        # Crear el modelo
        model = cplex.Cplex()
        model.set_results_stream(None) # deshabilito log de CPLEX de la info paso a paso
        model.objective.set_sense(model.objective.sense.maximize)
        model.parameters.timelimit.set(max_time)
        
        initial_time=model.get_time()

        # Variables
        n_vars = []
        x_vars = []
        y_vars = []

        # Añadir las variables n_i
        for i in I:
            var_name = f"n_{i}"
            model.variables.add(names=[var_name], types=[model.variables.type.binary])
            n_vars.append(var_name)

        # Añadir las variables x_j^i
        for i in I:
            x_vars_i = []
            for j in T:
                var_name = f"x_{j}^{i}"
                model.variables.add(names=[var_name], types=[model.variables.type.binary])
                x_vars_i.append(var_name)
            x_vars.append(x_vars_i)

        # Añadir las variables y_j^i para las posiciones rotadas
        for i in I:
            y_vars_i = []
            for j in T_rot:
                var_name = f"y_{j}^{i}"
                model.variables.add(names=[var_name], types=[model.variables.type.binary])
                y_vars_i.append(var_name)
            y_vars.append(y_vars_i)

        # Función objetivo: maximizar la suma de n_i
        objective = [1.0] * len(I)
        model.objective.set_linear(list(zip(n_vars, objective)))

        # Restricción 1: Cada punto del bin está ocupado por a lo sumo un ítem (incluyendo rotaciones)
        for index_p, _ in enumerate(P):
            indexes = []
            coefficients = []
            for i in I:
                for index_j, j in enumerate(T):
                    if C[index_j][index_p] == 1:
                        indexes.append(f"x_{j}^{i}")
                        coefficients.append(1.0)
                for index_j, j in enumerate(T_rot):
                    if C_rot[index_j][index_p] == 1:
                        indexes.append(f"y_{j}^{i}")
                        coefficients.append(1.0)
            constraint_rhs=1.0
            constraint_sense="L"
            add_constraint(model,coefficients,indexes,constraint_rhs,constraint_sense)

        # Restricción 2: No exceder el área del bin
        indexes = []
        coefficients = []
        seen_indices = set()

        for i in I:
            for index_j, j in enumerate(T):
                for index_p, _ in enumerate(P):
                    if C[index_j][index_p] == 1:
                        var_name = f"x_{j}^{i}"
                        if var_name not in seen_indices:
                            indexes.append(var_name)
                            coefficients.append(1.0)
                            seen_indices.add(var_name)
            for index_j, j in enumerate(T_rot):
                for index_p, _ in enumerate(P):
                    if C_rot[index_j][index_p] == 1:
                        var_name = f"y_{j}^{i}"
                        if var_name not in seen_indices:
                            indexes.append(var_name)
                            coefficients.append(1.0)
                            seen_indices.add(var_name)
        constraint_rhs=W * H
        constraint_sense="L"
        add_constraint(model,coefficients,indexes,constraint_rhs,constraint_sense)

        # Restricción 3: n_i <= suma(x_j^i + y_j^i)
        for i in I:
            indexes = [f"x_{j}^{i}" for j in T] + [f"y_{j}^{i}" for j in T_rot]
            coefficients = [1.0] * (len(T) + len(T_rot))
            indexes.append(f"n_{i}")
            coefficients.append(-1.0)
            constraint_rhs=0.0
            constraint_sense="G"
            add_constraint(model,coefficients,indexes,constraint_rhs,constraint_sense)

        # Restricción 4: suma(x_j^i) <= Q(i) * n_i
        for i in I:
            indexes = [f"x_{j}^{i}" for j in T]
            coefficients = [1.0] * len(T)
            indexes.append(f"n_{i}")
            coefficients.append(-Q)
            constraint_rhs=0.0
            constraint_sense="L"
            add_constraint(model,coefficients,indexes,constraint_rhs,constraint_sense)

        # Restricción 5: suma(y_j^i) <= Q_rot(i) * n_i
        for i in I:
            indexes = [f"y_{j}^{i}" for j in T_rot]
            coefficients = [1.0] * len(T_rot)
            indexes.append(f"n_{i}")
            coefficients.append(-Q_rot)
            constraint_rhs=0.0
            constraint_sense="L"
            add_constraint(model,coefficients,indexes,constraint_rhs,constraint_sense)

        # Desactivar la interrupción manual aquí
        manual_interruption.value = False

        # Resolver el modelo
        model.solve()
        objective_value = model.solution.get_objective_value()

        # Imprimir resultados
        print("Optimal value:", objective_value)
        
        # #imprimo valor que toman las variables
        # for i, var_name in enumerate(n_vars):
        #     print(f"{var_name} = {model.solution.get_values(var_name)}")


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

    except CplexSolverError as e:
        handle_solver_error(e, queue,solver_time)

def execute_with_time_limit(max_time):
    global model_status, solver_status, objective_value, solver_time 
    # Crear una cola para recibir los resultados del subproceso
    queue = multiprocessing.Queue()

    # Crear una variable compartida para manejar la interrupción manual
    manual_interruption = multiprocessing.Value('b', True)

    # Crear el subproceso que correrá la función
    process = multiprocessing.Process(target=create_and_solve_model, args=(queue, manual_interruption, max_time))

    # Iniciar el subproceso
    process.start()

    initial_time = time.time()

    # Monitorear la cola mientras el proceso está en ejecución
    while process.is_alive():
        if manual_interruption.value and time.time() - initial_time > max_time:
            print("Limit time reached. Aborting process.")
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
    return CASE_NAME, MODEL_NAME, model_status, solver_status, objective_value, solver_time
