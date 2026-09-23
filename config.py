"""Runtime flags and compatibility facade for the case repository.

The case catalog lives in :mod:`instances`; this module only keeps the legacy
configuration symbols used by older model modules and scripts.
"""

from instances import (
    CaseRepository,
    DEFAULT_CASE_NAME,
    DEFAULT_INSTANCES,
    REQUIRED_INSTANCE_FIELDS,
)

USE_PRACTICAL_CG_ENHANCEMENTS = False
INSTANCES = DEFAULT_INSTANCES


def _validate_positive_integer(case_name, instance, field_name):
    if field_name not in instance:
        raise ValueError(
            f"Invalid config for {case_name}: missing required field {field_name}"
        )
    value = instance[field_name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"Invalid config for {case_name}: {field_name} must be an integer"
        )
    if value <= 0:
        raise ValueError(
            f"Invalid config for {case_name}: {field_name} must be greater than 0"
        )


def _validate_instance(case_name, instance):
    """Compatibility hook; validation is implemented by ``CaseRepository``."""
    CaseRepository({case_name: instance}).get(case_name)


def _normalize_instance(case_name, instance):
    return CaseRepository({case_name: instance}).get(case_name)


def get_instance(case_name):
    return CaseRepository(INSTANCES).get(case_name)


def list_instance_names():
    return CaseRepository(INSTANCES).names()


def set_current_instance(case_name):
    global CASE_NAME, BIN_WIDTH, BIN_HEIGHT, ITEM_WIDTH, ITEM_HEIGHT, ITEMS_COUNT
    instance = get_instance(case_name)
    CASE_NAME = instance["case_name"]
    BIN_WIDTH = instance["bin_width"]
    BIN_HEIGHT = instance["bin_height"]
    ITEM_WIDTH = instance["item_width"]
    ITEM_HEIGHT = instance["item_height"]
    ITEMS_COUNT = (BIN_WIDTH * BIN_HEIGHT) // (ITEM_WIDTH * ITEM_HEIGHT)
    return instance


# Historical variables for scripts that still import config.*.
set_current_instance(DEFAULT_CASE_NAME)
