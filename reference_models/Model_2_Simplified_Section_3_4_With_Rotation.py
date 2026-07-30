import cplex
from cplex.exceptions import CplexSolverError
import multiprocessing
import time
from position_generator import generate_positions_castro
from Utils.model_functions import *
from Config import *

MODEL_NAME="Model2Pos1"

# Generación de posiciones factibles para ítems y sus versiones rotadas
SET_POS_X, SET_POS_Y, SET_POS_X_I, SET_POS_Y_I = generate_positions_castro(BIN_WIDTH, BIN_HEIGHT, ITEM_WIDTH, ITEM_HEIGHT)
SET_POS_X, SET_POS_Y, SET_POS_X_I_ROT, SET_POS_Y_I_ROT = generate_positions_castro(BIN_WIDTH, BIN_HEIGHT, ITEM_HEIGHT, ITEM_WIDTH)

QUANTITY_X_I = len(SET_POS_X_I)
QUANTITY_Y_I = len(SET_POS_Y_I)
QUANTITY_X_I_ROT = len(SET_POS_X_I_ROT)
QUANTITY_Y_I_ROT = len(SET_POS_Y_I_ROT)

def create_and_solve_model(queue, manual_interruption, max_time):
    #valores por default para enviar a paver
    model_status, solver_status, objective_value, solver_time = "1", "1", 0, 1

    try:
        # Crear el modelo CPLEX
        model = cplex.Cplex()
        model.set_results_stream(None) # deshabilito log de CPLEX de la info paso a paso
        model.set_problem_type(cplex.Cplex.problem_type.LP)
        model.objective.set_sense(model.objective.sense.maximize)
        model.parameters.timelimit.set(max_time)
        
        initial_time=model.get_time()
        
        # Definir variables y objetivos
        var_names = [f"m_{i}" for i in ITEMS] + [f"m_rot_{i}" for i in ITEMS]
        coeffs = [1.0] * ITEMS_COUNT * 2
        add_variables(model, var_names, coeffs, "B")

        position_var_names = []
        for i in ITEMS:
            for x in SET_POS_X_I:
                for y in SET_POS_Y_I:
                    position_var_names.append(f"n_{i},{x},{y}")
            for x_rot in SET_POS_X_I_ROT:
                for y_rot in SET_POS_Y_I_ROT:
                    position_var_names.append(f"n_rot_{i},{x_rot},{y_rot}")

        position_coeffs = [0.0] * len(position_var_names)
        add_variables(model, position_var_names, position_coeffs, "B")

        r_var_names = [f"r_{x},{y}" for x in SET_POS_X for y in SET_POS_Y]
        add_variables(model, r_var_names, [0.0] * len(r_var_names), "B")

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
                constraint_rhs=0.0
                constraint_sense="E"
                add_constraint(model,constraint_coeff,constraint_vars,constraint_rhs,constraint_sense)

        for i in ITEMS:
            constraint_coeff = [-1.0]  # Coeficiente para m_i
            constraint_vars = [f"m_{i}"]  # Variable m_i que indica si el ítem no rotated está en el bin

            # Sumamos todas las posiciones no rotadas posibles donde el ítem puede estar
            for x in SET_POS_X_I:
                for y in SET_POS_Y_I:
                    constraint_coeff.append(1.0)
                    constraint_vars.append(f"n_{i},{x},{y}")
            constraint_rhs=0.0
            constraint_sense="E"
            add_constraint(model,constraint_coeff,constraint_vars,constraint_rhs,constraint_sense)

        # Restricción para ítems rotados: m_rot_i = suma de las posiciones rotadas donde está el ítem i
        for i in ITEMS:
            constraint_coeff_rot = [-1.0]  # Coeficiente para m_rot_i
            constraint_vars_rot = [f"m_rot_{i}"]  # Variable m_rot_i que indica si el ítem rotated está en el bin

            # Sumamos todas las posiciones rotadas posibles donde el ítem puede estar
            for x_rot in SET_POS_X_I_ROT:
                for y_rot in SET_POS_Y_I_ROT:
                    constraint_coeff_rot.append(1.0)
                    constraint_vars_rot.append(f"n_rot_{i},{x_rot},{y_rot}")
            constraint_rhs=0.0
            constraint_sense="E"
            add_constraint(model,constraint_coeff_rot,constraint_vars_rot,constraint_rhs,constraint_sense)

        # Restricción 3: suma de posiciones <= Q(X_i)*Q(Y_i) * m_i
        for i in ITEMS:
            constraint_coeff = [-1.0]  # Coeficiente para m_i
            constraint_vars = [f"m_{i}"]

            for x in SET_POS_X_I:
                for y in SET_POS_Y_I:
                    constraint_coeff.append(1.0)
                    constraint_vars.append(f"n_{i},{x},{y}")
                    
            constraint_rhs=QUANTITY_X_I * QUANTITY_Y_I
            constraint_sense="L"    
            add_constraint(model,constraint_coeff,constraint_vars,constraint_rhs,constraint_sense)

            constraint_coeff_rot = [-1.0]  # Coeficiente para m_rot_i
            constraint_vars_rot = [f"m_rot_{i}"]

            for x_rot in SET_POS_X_I_ROT:
                for y_rot in SET_POS_Y_I_ROT:
                    constraint_coeff_rot.append(1.0)
                    constraint_vars_rot.append(f"n_rot_{i},{x_rot},{y_rot}")
            constraint_rhs=QUANTITY_X_I_ROT * QUANTITY_Y_I_ROT
            add_constraint(model,constraint_coeff_rot,constraint_vars_rot,constraint_rhs,constraint_sense)

        # Restricción 4: m_i + m_rot_i <= 1
        for i in ITEMS:
            add_constraint(model,[1.0, 1.0],[f"m_{i}", f"m_rot_{i}"],1.0,"L")

        # Desactivar la interrupción manual aquí
        manual_interruption.value = False

        # Resolver el modelo
        model.solve()

        # Obtener resultados
        objective_value = model.solution.get_objective_value()

        print("Optimal value:", objective_value)
        
        #aca imprimo el valor que toman las variables
        # for var_name, value in zip(var_names, solution_values):
        #     print(f"{var_name} = {value}")
        
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

