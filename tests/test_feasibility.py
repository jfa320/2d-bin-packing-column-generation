import time

import pytest

from models.column_generation.column_generation_solver import orchestrator
from objects.ConfigData import ConfigData
from helper_methods import validate_feasibility


class ItemDummy:
    def __init__(self, x, y, width, height):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    def get_position_x(self):
        return self.x

    def get_position_y(self):
        return self.y

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height


class SliceDummy:
    def __init__(self, items):
        self.items = items

    def get_items(self):
        return self.items


class TestOrchestratorFeasibility:
    def run_and_validate_feasibility(self, orchestrator_context, config_data, expected_value):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        objective_value, active_slices = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data,
            return_solution=True
        )

        assert objective_value is not None
        assert objective_value == expected_value

        validate_feasibility(
            active_slices,
            config_data.get_bin_width(),
            config_data.get_bin_height(),
            objective_value
        )

    def test_feasibility_case_1(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=6,
            bin_height=4,
            item_width=2,
            item_height=3
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=4)

    def test_feasibility_case_2(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=5,
            bin_height=5,
            item_width=3,
            item_height=2
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=4)

    def test_feasibility_new_optimum_case_6(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=6,
            bin_height=6,
            item_width=3,
            item_height=2
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=6)

    def test_feasibility_case_3(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=6,
            bin_height=6,
            item_width=4,
            item_height=2
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=4)

    def test_feasibility_case_4(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=7,
            bin_height=3,
            item_width=3,
            item_height=2
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=3)

    def test_feasibility_case_5(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=6,
            bin_height=3,
            item_width=3,
            item_height=2
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=3)

    def test_feasibility_case_6(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=120,
            bin_height=20,
            item_width=12,
            item_height=8
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=25)

    def test_feasibility_case_7(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=50,
            bin_height=20,
            item_width=13,
            item_height=8
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=7)

    def test_feasibility_case_8(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=40,
            bin_height=25,
            item_width=10,
            item_height=6
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=16)

    def test_feasibility_case_9(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=60,
            bin_height=20,
            item_width=12,
            item_height=7
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=13)

    def test_feasibility_case_10(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=45,
            bin_height=30,
            item_width=9,
            item_height=9
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=15)

    def test_feasibility_case_11(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=70,
            bin_height=25,
            item_width=14,
            item_height=8
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=15)

    def test_feasibility_case_12(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=55,
            bin_height=22,
            item_width=11,
            item_height=6
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=18)

    def test_feasibility_case_13(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=20,
            bin_height=20,
            item_width=6,
            item_height=5
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=12)

    def test_feasibility_case_14(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=40,
            bin_height=30,
            item_width=10,
            item_height=7
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=16)

    def test_feasibility_case_15(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=60,
            bin_height=25,
            item_width=12,
            item_height=5
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=25)

    def test_feasibility_case_16(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=48,
            bin_height=24,
            item_width=8,
            item_height=6
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=24)

    def test_feasibility_case_17(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=70,
            bin_height=28,
            item_width=14,
            item_height=7
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=20)

    def test_feasibility_case_18(self, orchestrator_context):
        config_data = ConfigData(
            bin_width=10,
            bin_height=30,
            item_width=1,
            item_height=6
        )

        self.run_and_validate_feasibility(orchestrator_context, config_data, expected_value=50)

    def test_feasibility_rompe_por_superposition(self):
        slices = [
            SliceDummy([
                ItemDummy(x=0, y=0, width=2, height=2),
                ItemDummy(x=1, y=1, width=2, height=2),
            ])
        ]

        with pytest.raises(AssertionError):
            validate_feasibility(
                slices,
                bin_width=5,
                bin_height=5,
                objective_value=2
            )
