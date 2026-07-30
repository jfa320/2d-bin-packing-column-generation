import argparse

import Model_1_Simplified_Section_2_8_No_Rotation
import Model_1_Simplified_Section_2_9_With_Rotation
from column_generation import column_generation_solver
import Model_6_Andrade_Birgin_Monoitem
import Model_7_Exact_Monoitem_Backtracking
from Config import DEFAULT_CASE_NAME, get_instance, list_instance_names
from trace_file_generator import TraceFileGenerator


DEFAULT_EXECUTION_TIME = 1200  # Execution time in seconds for each model; can be changed through the CLI.

MODELS = [
    column_generation_solver,
    Model_1_Simplified_Section_2_8_No_Rotation,
    Model_1_Simplified_Section_2_9_With_Rotation,
    Model_6_Andrade_Birgin_Monoitem,
    Model_7_Exact_Monoitem_Backtracking,
]


def parse_args():
    parser = argparse.ArgumentParser(description="Run models on one or more instances.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--case", default=DEFAULT_CASE_NAME, help="Instance to run.")
    group.add_argument("--cases", nargs="+", help="Instances to run.")
    group.add_argument("--all", action="store_true", help="Run all configured instances.")
    parser.add_argument("--time", type=int, default=DEFAULT_EXECUTION_TIME, help="Time limit per model in seconds.")
    parser.add_argument("--output", default="output.trc", help="Name of the .trc file inside Results.")
    return parser.parse_args()


def selected_case_names(args):
    if args.all:
        return list_instance_names()
    if args.cases:
        return args.cases
    return [args.case]


def main():
    args = parse_args()
    generator = TraceFileGenerator(args.output)

    for case_name in selected_case_names(args):
        instance = get_instance(case_name)
        print(
            f"Running {instance['case_name']}: "
            f"bin=({instance['bin_width']},{instance['bin_height']}), "
            f"item=({instance['item_width']},{instance['item_height']})"
        )

        for model in MODELS:
            print(f"Model: {model.MODEL_NAME}")
            case_name, model_name, model_status, solver_status, objective_value, solver_time = model.execute_with_time_limit(
                args.time,
                instance,
            )
            generator.write_trace_record(case_name, model_name, model_status, solver_status, objective_value, solver_time)


if __name__ == '__main__':
    main()
