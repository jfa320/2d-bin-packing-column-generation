import pytest

import Config


def test_get_instance_returns_normalized_valid_instance(monkeypatch):
    monkeypatch.setitem(Config.INSTANCES, "valid_case", {
        "bin_width": 10,
        "bin_height": 8,
        "item_width": 2,
        "item_height": 4,
        "optimum": 10,
    })

    instance = Config.get_instance("valid_case")

    assert instance == {
        "case_name": "valid_case",
        "bin_width": 10,
        "bin_height": 8,
        "item_width": 2,
        "item_height": 4,
        "optimum": 10,
    }


@pytest.mark.parametrize("field_name", ["bin_width", "bin_height", "item_width", "item_height"])
def test_get_instance_rejects_missing_required_fields(monkeypatch, field_name):
    instance = {
        "bin_width": 10,
        "bin_height": 8,
        "item_width": 2,
        "item_height": 4,
    }
    del instance[field_name]
    monkeypatch.setitem(Config.INSTANCES, "missing_field_case", instance)

    with pytest.raises(ValueError, match=f"Invalid config for missing_field_case: missing required field {field_name}"):
        Config.get_instance("missing_field_case")


@pytest.mark.parametrize("invalid_value", [0, -1])
@pytest.mark.parametrize("field_name", ["bin_width", "bin_height", "item_width", "item_height"])
def test_get_instance_rejects_non_positive_required_fields(monkeypatch, field_name, invalid_value):
    instance = {
        "bin_width": 10,
        "bin_height": 8,
        "item_width": 2,
        "item_height": 4,
    }
    instance[field_name] = invalid_value
    monkeypatch.setitem(Config.INSTANCES, "non_positive_case", instance)

    with pytest.raises(ValueError, match=f"Invalid config for non_positive_case: {field_name} must be greater than 0"):
        Config.get_instance("non_positive_case")


@pytest.mark.parametrize("invalid_value", ["1", 1.5, True, None])
@pytest.mark.parametrize("field_name", ["bin_width", "bin_height", "item_width", "item_height"])
def test_get_instance_rejects_non_integer_required_fields(monkeypatch, field_name, invalid_value):
    instance = {
        "bin_width": 10,
        "bin_height": 8,
        "item_width": 2,
        "item_height": 4,
    }
    instance[field_name] = invalid_value
    monkeypatch.setitem(Config.INSTANCES, "non_integer_case", instance)

    with pytest.raises(ValueError, match=f"Invalid config for non_integer_case: {field_name} must be an integer"):
        Config.get_instance("non_integer_case")


@pytest.mark.parametrize("invalid_value", [-1, "1", 1.5, True])
def test_get_instance_rejects_invalid_optimum(monkeypatch, invalid_value):
    monkeypatch.setitem(Config.INSTANCES, "invalid_optimum_case", {
        "bin_width": 10,
        "bin_height": 8,
        "item_width": 2,
        "item_height": 4,
        "optimum": invalid_value,
    })

    expected_message = "optimum must be greater than or equal to 0" if invalid_value == -1 else "optimum must be an integer"
    with pytest.raises(ValueError, match=f"Invalid config for invalid_optimum_case: {expected_message}"):
        Config.get_instance("invalid_optimum_case")


def test_get_instance_accepts_missing_optimum(monkeypatch):
    monkeypatch.setitem(Config.INSTANCES, "no_optimum_case", {
        "bin_width": 10,
        "bin_height": 8,
        "item_width": 2,
        "item_height": 4,
    })

    instance = Config.get_instance("no_optimum_case")

    assert instance["optimum"] is None
