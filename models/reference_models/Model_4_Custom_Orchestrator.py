from models.reference_models.Model_4_Custom_Master import create_and_solve_master_model
from models.reference_models.Model_4_Custom_Slave import create_and_solve_slave_model, find_highest_height

from objects import Slice
from objects import Item

import multiprocessing
import time

from utils.trace_file_generator import TraceFileGenerator

MODEL_NAME="Model4"

model_status="1"
solver_status="1"
objective_value=0
solver_time=1
results_path=""
FIXED_SLICE_HEIGHT=2
BIN_WIDTH=5
ITEMS_EMPAQUETAR = [
    Item(height=height, width=1, rotated=rotated, position_y=position_y)
    for height, position_y, rotated in [(10, 5, True), (5, 30, False)]
]
MAX_SECONDS=5    
    
CASE_NAME="inst2"
    
def get_initial_slice(bin_width, items):
    current_width=0
    slice_items=[]
    for item in items:
        if(current_width<=bin_width):
            current_width=current_width+item.get_width()
            slice_items.append(item)
    slice_height = find_highest_height(slice_items) or 1
    slice = Slice(height=slice_height, width=bin_width, items=slice_items)
    
    return slice        

def execute_models(manual_interruption):
    global results_path

    initial_slice=get_initial_slice(BIN_WIDTH,ITEMS_EMPAQUETAR)
    dual_solution=create_and_solve_master_model(manual_interruption,MAX_SECONDS,initial_slice) 
    slice=create_and_solve_slave_model(dual_solution)
    
    while(slice!=0):
        add_new_variable_new_constraints_master_model(slice)
        dual_solution=solve_master_model(slice)
        slice=create_and_solve_slave_model(dual_solution)
    results_path=final_solve_master_model(slice)        
      
def execute_with_time_limit(max_seconds, function_to_execute, *args):
    global model_status, solver_status, objective_value, solver_time 

    queue = multiprocessing.Queue()

    manual_interruption = multiprocessing.Value('b', True)

    process = multiprocessing.Process(target=function_to_execute, args=(queue,manual_interruption,*args))

    process.start()

    start_time = time.time()
    successful_process = False

    while process.is_alive():

        if manual_interruption.value:
            if time.time() - start_time > max_seconds:
                print("Time limit reached. Aborting process.")
                model_status="14"
                solver_status="4"
                solver_time=max_seconds
                process.terminate()
                process.join()
                break
        else:
            successful_process = True        
        time.sleep(0.1)

    if successful_process:
        print("Successful execution. See generated results in paver file: "+results_path)    
        
    while not queue.empty():
        message = queue.get()
        if isinstance(message, dict):
            print(message)
            model_status = message["model_status"]
            solver_status = message["solver_status"]
            objective_value = message["objective_value"]
            solver_time = message["solver_time"]
            

if __name__ == '__main__':
    
    execute_with_time_limit(MAX_SECONDS,execute_models)
    generator = TraceFileGenerator("output.trc")
    generator.write_trace_record(CASE_NAME, MODEL_NAME, model_status, solver_status, objective_value, solver_time)
