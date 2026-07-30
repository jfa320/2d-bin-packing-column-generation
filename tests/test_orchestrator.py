import time

import pytest
from column_generation.column_generation_solver import orchestrator
from Objects.ConfigData import ConfigData

class TestOrchestrator:
    def test_case_1(self, orchestrator_context):
        
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=6,        # W
            bin_height=4,       # H
            item_width=2,       # w
            item_height=3       # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 4  # Expected optimal value for case 1

   
    def test_case_2(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=5,        # W
            bin_height=5,       # H
            item_width=3,       # w
            item_height=2       # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 4  # Expected optimal value for case 2

    def test_new_optimum_case_6(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=6,        # W
            bin_height=6,       # H
            item_width=3,       # w
            item_height=2       # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 6  # Expected optimal value
        

    def test_case_3(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=6,        # W
            bin_height=6,       # H
            item_width=4,       # w
            item_height=2       # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 4
        
    def test_case_4(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=7,        # W
            bin_height=3,       # H
            item_width=3,       # w
            item_height=2       # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 3

    def test_case_5(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=6,        # W
            bin_height=3,       # H
            item_width=3,       # w
            item_height=2       # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 3

    def test_case_6(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=120,       # W
            bin_height=20,       # H
            item_width=12,       # w
            item_height=8        # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 25
    
    # OR Library large cases start here

    def test_case_7(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=50,        # W
            bin_height=20,       # H
            item_width=13,       # w
            item_height=8        # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 7


    def test_case_8(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=40,        # W
            bin_height=25,       # H
            item_width=10,       # w
            item_height=6        # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 16

    def test_case_9(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=60,        # W
            bin_height=20,       # H
            item_width=12,       # w
            item_height=7        # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 13

    def test_case_10(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=45,        # W
            bin_height=30,       # H
            item_width=9,        # w
            item_height=9        # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 15
    
    def test_case_11(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=70,        # W
            bin_height=25,       # H
            item_width=14,       # w
            item_height=8        # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 15

    def test_case_12(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=55,        # W
            bin_height=22,       # H
            item_width=11,       # w
            item_height=6        # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 18

    def test_case_13(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=20,        # W
            bin_height=20,       # H
            item_width=6,        # w
            item_height=5        # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 12
        

    def test_case_14(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=40,        # W
            bin_height=30,       # H
            item_width=10,       # w
            item_height=7        # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 16

    def test_case_15(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=60,        # W
            bin_height=25,       # H
            item_width=12,       # w
            item_height=5        # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 25

    def test_case_16(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=48,        # W
            bin_height=24,       # H
            item_width=8,        # w
            item_height=6        # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 24

    def test_case_17(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=70,        # W
            bin_height=28,       # H
            item_width=14,       # w
            item_height=7        # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 20

    def test_case_18(self, orchestrator_context):
        queue, manual_interruption, EXECUTION_TIME = orchestrator_context

        config_data = ConfigData(
            bin_width=10,        # W
            bin_height=30,       # H
            item_width=1,        # w
            item_height=6        # h
        )

        objective_value = orchestrator(
            queue,
            manual_interruption,
            EXECUTION_TIME,
            time.time(),
            config_data
        )

        assert objective_value is not None
        assert objective_value == 50


