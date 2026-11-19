"""Timed adapter for the Big-M adaptation of Andrade and Birgin (2013).

Symmetry-breaking constraints for packing identical rectangles within polyhedra.
Optimization Letters 7, 375-405. DOI: 10.1007/s11590-011-0425-9.
The local paper is the 2011 preprint; the final journal volume is dated 2013.
"""

from functools import partial

from config import (
    BIN_HEIGHT, BIN_WIDTH, CASE_NAME, ITEM_HEIGHT, ITEM_WIDTH, get_instance,
)
from models.comparative.andrade_birgin_2013_model import AndradeBirgin2013ModelBuilder
from utils.execution_result import ExecutionResult
from utils.execution_runner import TimedModelExecutor
from utils.model_runner import run_model, solve_lp_model, solve_mip_model
from utils.paver_constants import PaverConstants as PAVER

MODEL_NAME = "AndradeBirgin2013BigM"


def _builder_from_globals():
    return AndradeBirgin2013ModelBuilder(
        BIN_WIDTH, BIN_HEIGHT, ITEM_WIDTH, ITEM_HEIGHT
    )


_MODEL_BUILDER = _builder_from_globals()


def apply_instance(instance):
    global CASE_NAME, BIN_WIDTH, BIN_HEIGHT, ITEM_WIDTH, ITEM_HEIGHT, _MODEL_BUILDER
    CASE_NAME = instance["case_name"]
    BIN_WIDTH = instance["bin_width"]
    BIN_HEIGHT = instance["bin_height"]
    ITEM_WIDTH = instance["item_width"]
    ITEM_HEIGHT = instance["item_height"]
    _MODEL_BUILDER = _builder_from_globals()


def calculate_physical_item_bound():
    return _MODEL_BUILDER.physical_item_bound()


def create_model(max_time):
    return _MODEL_BUILDER.build(max_time)


def solve_model(model):
    return solve_mip_model(model, CASE_NAME, MODEL_NAME)


def run_model_for_instance(queue, max_time, instance, *, mode="mip", random_seed=None, threads=None):
    apply_instance(instance)
    solve = (partial(solve_lp_model, case_name=CASE_NAME, model_name=MODEL_NAME)
             if mode == "lp" else solve_model)
    run_model(create_model, solve, queue, max_time, CASE_NAME, MODEL_NAME,
              report_mip_incumbents=mode == "mip", random_seed=random_seed, threads=threads)


_EXECUTORS = {
    "mip": TimedModelExecutor(run_model_for_instance, MODEL_NAME, get_instance, lambda: CASE_NAME),
    "lp": TimedModelExecutor(partial(run_model_for_instance, mode="lp"), MODEL_NAME,
                             get_instance, lambda: CASE_NAME,
                             feasible_status=PAVER.MODEL_STATUS_LP_FEASIBLE),
}


def execute_with_time_limit(max_time, instance=None, *, mode="mip",
                            random_seed=None, threads=None) -> ExecutionResult:
    """Solve the integer model or its continuous relaxation within a wall limit."""
    if mode not in ("mip", "lp"):
        raise ValueError("mode must be 'mip' or 'lp'")
    return _EXECUTORS[mode].execute_with_time_limit(
        max_time, instance, random_seed=random_seed, threads=threads)
