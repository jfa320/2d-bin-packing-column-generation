"""Pure model builder for the Andrade--Birgin mono-item formulation."""

import cplex

from utils.cplex_helpers import add_constraint, add_variables


class AndradeBirginModelBuilder:
    def __init__(self, bin_width, bin_height, item_width, item_height):
        self.bin_width = bin_width
        self.bin_height = bin_height
        self.item_width = item_width
        self.item_height = item_height

    def physical_item_bound(self):
        return (self.bin_width * self.bin_height) // (
            self.item_width * self.item_height
        )

    def build(self, max_time):
        model = cplex.Cplex()
        model.set_results_stream(None)
        model.set_problem_type(cplex.Cplex.problem_type.MILP)
        model.objective.set_sense(model.objective.sense.maximize)
        model.parameters.timelimit.set(max_time)

        max_item_dim = max(self.item_width, self.item_height)
        big_m_x = 2 * self.bin_width + 2 * max_item_dim
        big_m_y = 2 * self.bin_height + 2 * max_item_dim
        items = list(range(1, self.physical_item_bound() + 1))

        add_variables(model, [f"f_{i}" for i in items], [1.0] * len(items), "B")
        add_variables(model, [f"r_{i}" for i in items], [0.0] * len(items), "B")
        centers = [f"cx_{i}" for i in items] + [f"cy_{i}" for i in items]
        add_variables(model, centers, [0.0] * len(centers), "C")
        effective = [f"wEff_{i}" for i in items] + [f"hEff_{i}" for i in items]
        add_variables(model, effective, [0.0] * len(effective), "C")

        relative = []
        for i in items:
            for j in items:
                if i < j:
                    relative.extend([f"q_{i},{j}", f"q_{j},{i}"])
        add_variables(model, relative, [0.0] * len(relative), "B")

        delta = self.item_height - self.item_width
        for i in items:
            add_constraint(model, [1.0, -delta], [f"wEff_{i}", f"r_{i}"], self.item_width, "E")
            add_constraint(model, [1.0, delta], [f"hEff_{i}", f"r_{i}"], self.item_height, "E")

        for i in items:
            add_constraint(model, [1.0, -0.5], [f"cx_{i}", f"wEff_{i}"], 0.0, "G")
            add_constraint(model, [1.0, 0.5], [f"cx_{i}", f"wEff_{i}"], self.bin_width, "L")
            add_constraint(model, [1.0, -0.5], [f"cy_{i}", f"hEff_{i}"], 0.0, "G")
            add_constraint(model, [1.0, 0.5], [f"cy_{i}", f"hEff_{i}"], self.bin_height, "L")

        for i in items:
            for j in items:
                if i >= j:
                    continue
                q_ij, q_ji = f"q_{i},{j}", f"q_{j},{i}"
                add_constraint(
                    model, [1.0, -1.0, -0.5, -0.5, big_m_x, big_m_x],
                    [f"cx_{i}", f"cx_{j}", f"wEff_{i}", f"wEff_{j}", q_ij, q_ji],
                    0.0, "G",
                )
                add_constraint(
                    model, [1.0, -1.0, -0.5, -0.5, -big_m_x, -big_m_x],
                    [f"cx_{j}", f"cx_{i}", f"wEff_{i}", f"wEff_{j}", q_ij, q_ji],
                    -2 * big_m_x, "G",
                )
                add_constraint(
                    model, [1.0, -1.0, -0.5, -0.5, -big_m_y, big_m_y],
                    [f"cy_{i}", f"cy_{j}", f"hEff_{i}", f"hEff_{j}", q_ij, q_ji],
                    -big_m_y, "G",
                )
                add_constraint(
                    model, [1.0, -1.0, -0.5, -0.5, big_m_y, -big_m_y],
                    [f"cy_{j}", f"cy_{i}", f"hEff_{i}", f"hEff_{j}", q_ij, q_ji],
                    -big_m_y, "G",
                )
        return model
