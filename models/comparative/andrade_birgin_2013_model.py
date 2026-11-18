"""Big-M model builder adapted from Andrade and Birgin (2013).

Symmetry-breaking constraints for packing identical rectangles within polyhedra.
Optimization Letters 7, 375-405. DOI: 10.1007/s11590-011-0425-9.
Uses the Section 2, equation (4) formulation for a rectangular bin; it does not
include the symmetry-breaking constraints introduced in Section 3.
Optional selection is a local extension: containment is active for selected
items and the four separation inequalities are active for selected pairs.
"""

import cplex

from utils.cplex_helpers import add_constraint, add_variables


class AndradeBirgin2013ModelBuilder:
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
        containment_m = 0.5 * max_item_dim
        M_w = 2 * self.bin_width + 2 * max_item_dim
        M_h = 2 * self.bin_height + 2 * max_item_dim
        items = list(range(1, self.physical_item_bound() + 1))

        add_variables(model, [f"f_{i}" for i in items], [1.0] * len(items), "B")
        add_variables(model, [f"r_{i}" for i in items], [0.0] * len(items), "B")
        centers = [f"cx_{i}" for i in items] + [f"cy_{i}" for i in items]
        add_variables(model, centers, [0.0] * len(centers), "C")
        # Keep these bounds even for omitted items. With effective dimensions
        # <= max_item_dim, they make all selection deactivations valid.
        model.variables.set_upper_bounds(
            [(f"cx_{i}", self.bin_width) for i in items]
            + [(f"cy_{i}", self.bin_height) for i in items]
        )
        effective = [f"w_{i}" for i in items] + [f"h_{i}" for i in items]
        add_variables(model, effective, [0.0] * len(effective), "C")

        relative = []
        for i in items:
            for j in items:
                if i < j:
                    relative.extend([f"q_{i},{j}", f"q_{j},{i}"])
        add_variables(model, relative, [0.0] * len(relative), "B")

        delta = self.item_height - self.item_width
        for i in items:
            add_constraint(model, [1.0, -delta], [f"w_{i}", f"r_{i}"], self.item_width, "E")
            add_constraint(model, [1.0, delta], [f"h_{i}", f"r_{i}"], self.item_height, "E")

        for i in items:
            # Original containment when f_i=1; redundant within the center
            # bounds when f_i=0, even if neither orientation fits the bin.
            add_constraint(
                model, [1.0, -0.5, -containment_m],
                [f"cx_{i}", f"w_{i}", f"f_{i}"], -containment_m, "G",
            )
            add_constraint(
                model, [1.0, 0.5, containment_m],
                [f"cx_{i}", f"w_{i}", f"f_{i}"],
                self.bin_width + containment_m, "L",
            )
            add_constraint(
                model, [1.0, -0.5, -containment_m],
                [f"cy_{i}", f"h_{i}", f"f_{i}"], -containment_m, "G",
            )
            add_constraint(
                model, [1.0, 0.5, containment_m],
                [f"cy_{i}", f"h_{i}", f"f_{i}"],
                self.bin_height + containment_m, "L",
            )

        # Subtract M * (2-f_i-f_j) from each original right-hand side.
        # For a selected pair this is exactly equation (4). Otherwise every
        # branch is redundant: cx_i-cx_j-(w_i+w_j)/2 >= -W-max_item_dim,
        # and M_w >= W+max_item_dim (analogously in y).
        for i in items:
            for j in items:
                if i >= j:
                    continue
                q_ij, q_ji = f"q_{i},{j}", f"q_{j},{i}"
                add_constraint(
                    model, [1.0, -1.0, -0.5, -0.5, M_w, M_w,
                            -M_w, -M_w],
                    [f"cx_{i}", f"cx_{j}", f"w_{i}", f"w_{j}",
                     q_ij, q_ji, f"f_{i}", f"f_{j}"],
                    -2 * M_w, "G",
                )
                add_constraint(
                    model, [1.0, -1.0, -0.5, -0.5, -M_w, -M_w,
                            -M_w, -M_w],
                    [f"cx_{j}", f"cx_{i}", f"w_{i}", f"w_{j}",
                     q_ij, q_ji, f"f_{i}", f"f_{j}"],
                    -4 * M_w, "G",
                )
                add_constraint(
                    model, [1.0, -1.0, -0.5, -0.5, -M_h, M_h,
                            -M_h, -M_h],
                    [f"cy_{i}", f"cy_{j}", f"h_{i}", f"h_{j}",
                     q_ij, q_ji, f"f_{i}", f"f_{j}"],
                    -3 * M_h, "G",
                )
                add_constraint(
                    model, [1.0, -1.0, -0.5, -0.5, M_h, -M_h,
                            -M_h, -M_h],
                    [f"cy_{j}", f"cy_{i}", f"h_{i}", f"h_{j}",
                     q_ij, q_ji, f"f_{i}", f"f_{j}"],
                    -3 * M_h, "G",
                )
        return model
