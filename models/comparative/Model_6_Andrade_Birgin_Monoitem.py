"""Timed execution adapter for the Andrade--Birgin model."""

from config import (
    BIN_HEIGHT, BIN_WIDTH, CASE_NAME, ITEM_HEIGHT, ITEM_WIDTH, get_instance,
)
from models.comparative.andrade_birgin_model import AndradeBirginModelBuilder
from utils.execution_result import ExecutionResult
from utils.execution_runner import TimedModelExecutor
from utils.model_functions import run_model, solve_mip_model

MODEL_NAME = "AndradeBirginBigM"


def _builder_from_globals():
    return AndradeBirginModelBuilder(
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


def run_model_for_instance(queue, max_time, instance):
    apply_instance(instance)
    run_model(create_model, solve_model, queue, max_time, CASE_NAME, MODEL_NAME)


_EXECUTOR = TimedModelExecutor(
    run_model_for_instance, MODEL_NAME, get_instance, lambda: CASE_NAME
)


def execute_with_time_limit(max_time, instance=None) -> ExecutionResult:
    return _EXECUTOR.execute_with_time_limit(max_time, instance)
