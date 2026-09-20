import argparse
import time

from models.column_generation import column_generation_solver
from models.comparative import Model_1_Simplified_Section_2_8_No_Rotation
from models.comparative import Model_1_Simplified_Section_2_9_With_Rotation
from models.comparative import Model_6_Andrade_Birgin_Monoitem
from models.comparative import Model_7_Exact_Monoitem_Backtracking
from config import DEFAULT_CASE_NAME, get_instance, list_instance_names
from utils.trace_file_generator import TraceFileGenerator
from utils.execution_result import ExecutionResult
from utils.paver_constants import PaverConstants
from utils.paver_runner import run_paver


DEFAULT_EXECUTION_TIME = 1200  # Execution time in seconds for each model; can be changed through the CLI.
PAVER = PaverConstants

MODELS = [
    column_generation_solver,
    Model_1_Simplified_Section_2_8_No_Rotation,
    Model_1_Simplified_Section_2_9_With_Rotation,
    Model_6_Andrade_Birgin_Monoitem,
    Model_7_Exact_Monoitem_Backtracking,
]


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run models on one or more instances.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--case", default=DEFAULT_CASE_NAME, help="Instance to run.")
    group.add_argument("--cases", nargs="+", help="Instances to run.")
    group.add_argument("--all", action="store_true", help="Run all configured instances.")
    parser.add_argument("--time", type=int, default=DEFAULT_EXECUTION_TIME, help="Time limit per model in seconds.")
    parser.add_argument("--output", default="output.trc", help="Name of the .trc file inside Results.")
    parser.add_argument("--append", action="store_true", help="Append only new instance/model pairs to a compatible trace.")
    paver_group = parser.add_mutually_exclusive_group()
    paver_group.add_argument(
        "--paver", dest="run_paver", action="store_true",
        help="Run PAVER after the trace is generated (default).",
    )
    paver_group.add_argument(
        "--no-paver", dest="run_paver", action="store_false",
        help="Only generate the trace; do not run PAVER.",
    )
    parser.set_defaults(run_paver=True)
    parser.add_argument(
        "--paver-path", default=None,
        help=("Override the PAVER root directory configured in "
              f"{PAVER.PAVER_PROPERTIES_FILENAME}."),
    )
    parser.add_argument(
        "--paver-output", default=None,
        help="Directory for the PAVER HTML report (defaults to Results/<trace>_paver).",
    )
    args = parser.parse_args(argv)
    if args.time <= 0:
        parser.error("--time must be positive")
    return args


def selected_case_names(args):
    if args.all:
        return list_instance_names()
    if args.cases:
        return args.cases
    return [args.case]


def main(argv=None):
    args = parse_args(argv)
    cases = selected_case_names(args)
    if len(cases) != len(set(cases)):
        raise ValueError("Duplicate case identifiers are not allowed")
    instances = [get_instance(case_name) for case_name in cases]
    generator = TraceFileGenerator(args.output, mode="append" if args.append else "overwrite")

    for instance in instances:

        for model in MODELS:
            print(f"Model: {model.MODEL_NAME}")
            started = time.perf_counter()
            try:
                result = model.execute_with_time_limit(args.time, instance)
            except Exception as error:
                result = ExecutionResult(
                    instance["case_name"], model.MODEL_NAME, PAVER.MODEL_STATUS_ERROR,
                    PAVER.TERMINATION_ERROR, None,
                    time.perf_counter() - started, error_message=str(error),
                )
            generator.write_trace_record(result)

    if args.run_paver:
        paver_result = run_paver(
            generator.path,
            args.paver_path,
            args.paver_output,
            failtime=args.time,
        )
        if paver_result.success:
            print(paver_result.message)
        else:
            # PAVER is an optional post-processing step. Its failure must not
            # erase or invalidate the trace produced by the model executions.
            print(f"ERROR: {paver_result.message}")


if __name__ == '__main__':
    main()
