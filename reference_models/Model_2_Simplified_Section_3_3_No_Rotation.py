import cplex
from cplex.exceptions import CplexSolverError
import multiprocessing
import time
from position_generator import generate_positions_castro
from Utils.model_functions import *
from Config import *

#Basado en la simplificacion del modelo 2 del overleaf (modelo discretizado en posiciones) - ver seccion 3.3 de ese documento para modelo completo

MODEL_NAME="Model2Pos1"

#SET_POS_X  constante X en el modelo
#SET_POS_Y  constante Y en el modelo

#SET_POS_X_I constante X_i en el modelo
#SET_POS_Y_I constante Y_i en el modelo

SET_POS_X, SET_POS_Y, SET_POS_X_I, SET_POS_Y_I = generate_positions_castro(BIN_WIDTH, BIN_HEIGHT, ITEM_WIDTH, ITEM_HEIGHT)

QUANTITY_X_I=len(SET_POS_X_I) #constante Q(X_i) del modelo
QUANTITY_Y_I=len(SET_POS_Y_I) #constante Q(Y_i) del modelo

def create_and_solve_model(queue, manual_interruption, max_time):
    #valores por default para enviar a paver
    model_status, solver_status, objective_value, solver_time = "1", "1", 0, 1

    try:
        # Crear un modelo de CPLEX
        model= cplex.Cplex()
        model.set_results_stream(None) # deshabilito log de CPLEX de la info paso a paso
        model.set_problem_type(cplex.Cplex.problem_type.LP)
        model.objective.set_sense(model.objective.sense.maximize)
        model.parameters.timelimit.set(max_time)

        initial_time=model.get_time()

        # Definir variables y objetivos
        var_names = [f"m_{i}" for i in range(1, ITEMS_COUNT + 1)]
        coeffs = [1.0] * ITEMS_COUNT  
        add_variables(model, var_names, coeffs, "B")

        additional_var_names = []
        for x in SET_POS_X_I:
            for y in SET_POS_Y_I:
                    for i in ITEMS:
                        additional_var_names.append(f"n_{i},{x},{y}") 

        for x in SET_POS_X:
            for y in SET_POS_Y:            
                additional_var_names.append(f"r_{x},{y}") 
        additional_obj_coeffs = [0.0] * len(additional_var_names)
        add_variables(model, additional_var_names, additional_obj_coeffs, "B")

        # Añadir la restricción r_{x,y} = sum_{i in N} sum_{x' in X_i, x-w+1 <= x' <= x} sum_{y' in Y_i, y-h+1 <= y' <= y} n_{i,x',y'} para cada (x, y) en X x Y
        for x in SET_POS_X:
            for y in SET_POS_Y:
                constraint_coeff = [1.0] 
                constraint_vars = [f"r_{x},{y}"]  
                for i in ITEMS:
                    for x_prime in SET_POS_X_I:
                        if x - ITEM_WIDTH + 1 <= x_prime <= x:
                            for y_prime in SET_POS_Y_I:
                                if y - ITEM_HEIGHT + 1 <= y_prime <= y:
                                    constraint_coeff.append(-1.0)
                                    constraint_vars.append(f"n_{i},{x_prime},{y_prime}")
                constraint_rhs = 0.0  
                constraint_sense = "E"  
                add_constraint(model,constraint_coeff,constraint_vars,constraint_rhs,constraint_sense)

        # Añadir la restricción m_i <= sum_{x in X_i} sum_{y in Y_i} n_{i,x,y} para cada i en items - restriccion 2 del modelo
        for i in ITEMS:
            constraint_coeff = [1.0]  # Coeficiente para m_i
            constraint_vars = [f"m_{i}"]  # Variable m_i
            # Añadir los coeficientes y variables de sum_{x in X_i} sum_{y in Y_i} n_{i,x,y}
            for x in SET_POS_X_I:
                for y in SET_POS_Y_I:
                    constraint_coeff.append(-1.0)
                    constraint_vars.append(f"n_{i},{x},{y}")
            constraint_rhs = 0.0  # Lado derecho de la restricción
            constraint_sense = "L"  # "L" indica <=
            add_constraint(model,constraint_coeff,constraint_vars,constraint_rhs,constraint_sense)

        # Añadir la restricción sum_{x in X_i} sum_{y in Y_i} n_{i,x,y} <= Q(X_i) Q(Y_i) m_i para cada i en items
        for i in ITEMS:
            constraint_coeff = [-1.0]  # Coeficiente para m_i
            constraint_vars = [f"m_{i}"]  # Variable m_i

            # Añadir los coeficientes y variables de sum_{x in X_i} sum_{y in Y_i} n_{i,x,y}
            for x in SET_POS_X_I:
                for y in SET_POS_Y_I:
                    constraint_coeff.append(1.0)
                    constraint_vars.append(f"n_{i},{x},{y}")
            constraint_rhs = 0.0  # Lado derecho de la restricción
            constraint_sense = "L"  # "L" indica <=
            add_constraint(model,constraint_coeff,constraint_vars,constraint_rhs,constraint_sense)

        # Desactivar la interrupción manual aquí
        manual_interruption.value = False

        # Resolver el modelo
        model.solve()

        # Obtener y mostrar los resultados
        objective_value = model.solution.get_objective_value()

        print("Optimal value:", objective_value)
        
        # print("Variables values:")
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

