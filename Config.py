# Shared instance catalog for models and PAVER.

DEFAULT_CASE_NAME = "case7"

# Enables practical enhancements used to improve column diversity and robustness.
# Set to False to run a cleaner canonical column-generation loop.
USE_PRACTICAL_CG_ENHANCEMENTS = False

REQUIRED_INSTANCE_FIELDS = ("bin_width", "bin_height", "item_width", "item_height")

INSTANCES = {
    "case1": {
        "bin_width": 6,
        "bin_height": 4,
        "item_width": 2,
        "item_height": 3,
        "optimum": 4,
    },
    "case2": {
        "bin_width": 5,
        "bin_height": 5,
        "item_width": 3,
        "item_height": 2,
    },
    "case3": {
        "bin_width": 6,
        "bin_height": 6,
        "item_width": 4,
        "item_height": 2,
        "optimum": 4,
    },
    "case4": {
        "bin_width": 7,
        "bin_height": 3,
        "item_width": 3,
        "item_height": 2,
        "optimum": 3,
    },
    "case5": {
        "bin_width": 6,
        "bin_height": 3,
        "item_width": 3,
        "item_height": 2,
        "optimum": 3,
    },
    "case6": {
        "bin_width": 120,
        "bin_height": 20,
        "item_width": 12,
        "item_height": 8,
        "optimum": 25,
    },
    "case7": {
        "bin_width": 50,
        "bin_height": 20,
        "item_width": 13,
        "item_height": 8,
        "optimum": 7,
    },
    "case8": {
        "bin_width": 40,
        "bin_height": 25,
        "item_width": 10,
        "item_height": 6,
        "optimum": 16,
    },
    "case9": {
        "bin_width": 60,
        "bin_height": 20,
        "item_width": 12,
        "item_height": 7,
        "optimum": 13,
    },
    "case10": {
        "bin_width": 45,
        "bin_height": 30,
        "item_width": 9,
        "item_height": 9,
        "optimum": 15,
    },
    "case11": {
        "bin_width": 70,
        "bin_height": 25,
        "item_width": 14,
        "item_height": 8,
        "optimum": 15,
    },
    "case12": {
        "bin_width": 55,
        "bin_height": 22,
        "item_width": 11,
        "item_height": 6,
        "optimum": 18,
    },
    "case13": {
        "bin_width": 20,
        "bin_height": 20,
        "item_width": 6,
        "item_height": 5,
        "optimum": 12,
    },
    "case14": {
        "bin_width": 40,
        "bin_height": 30,
        "item_width": 10,
        "item_height": 7,
        "optimum": 16,
    },
    "case15": {
        "bin_width": 60,
        "bin_height": 25,
        "item_width": 12,
        "item_height": 5,
        "optimum": 25,
    },
    "case16": {
        "bin_width": 48,
        "bin_height": 24,
        "item_width": 8,
        "item_height": 6,
        "optimum": 24,
    },
    "case17": {
        "bin_width": 70,
        "bin_height": 28,
        "item_width": 14,
        "item_height": 7,
        "optimum": 20,
    },
    "case18": {
        "bin_width": 10,
        "bin_height": 30,
        "item_width": 1,
        "item_height": 6,
        "optimum": 50,
    },
}


def _validate_positive_integer(case_name, instance, field_name):
    value = instance[field_name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Invalid config for {case_name}: {field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"Invalid config for {case_name}: {field_name} must be greater than 0")


def _validate_instance(case_name, instance):
    for field_name in REQUIRED_INSTANCE_FIELDS:
        if field_name not in instance:
            raise ValueError(f"Invalid config for {case_name}: missing required field {field_name}")
        _validate_positive_integer(case_name, instance, field_name)

    if "optimum" in instance and instance["optimum"] is not None:
        optimum = instance["optimum"]
        if isinstance(optimum, bool) or not isinstance(optimum, int):
            raise ValueError(f"Invalid config for {case_name}: optimum must be an integer")
        if optimum < 0:
            raise ValueError(f"Invalid config for {case_name}: optimum must be greater than or equal to 0")


def _normalize_instance(case_name, instance):
    _validate_instance(case_name, instance)
    return {
        "case_name": case_name,
        "bin_width": instance["bin_width"],
        "bin_height": instance["bin_height"],
        "item_width": instance["item_width"],
        "item_height": instance["item_height"],
        "optimum": instance.get("optimum"),
    }


def get_instance(case_name):
    if case_name not in INSTANCES:
        available = ", ".join(sorted(INSTANCES))
        raise ValueError(f"Unknown instance '{case_name}'. Available: {available}")
    return _normalize_instance(case_name, INSTANCES[case_name])


def list_instance_names():
    return sorted(INSTANCES)


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


# Historical variables for scripts that still import Config.*
set_current_instance(DEFAULT_CASE_NAME)
