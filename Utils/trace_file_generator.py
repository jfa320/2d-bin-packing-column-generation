import os

class TraceFileGenerator:
    def __init__(self, filename):
        self.filename = filename

    def write_trace_record(self, input_file_name, solver_name, model_status, solver_status, objective_value, solver_time):
            # Create the output folder only when this method is called.
            directory = "Results"
            if not os.path.exists(directory):
                os.makedirs(directory)
            
            # Save the file inside the output folder.
            full_path = os.path.join(directory, self.filename)

            with open(full_path, 'a') as file:
                # Write headers if the file is empty.
                if file.tell() == 0:
                    file.write("* Trace Record Definition\n")
                    file.write("* InputFileName,SolverName,ModelStatus,SolverStatus,ObjectiveValue,SolverTime\n")
                
                # Write data.
                file.write(f"{input_file_name},{solver_name},{model_status},{solver_status},{objective_value},{solver_time}\n")


