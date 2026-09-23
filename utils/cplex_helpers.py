"""Small helpers for constructing CPLEX models."""

import cplex


def add_variables(model, var_names, obj_coeffs, var_type):
    n = len(var_names)
    model.variables.add(
        names=var_names,
        obj=obj_coeffs,
        lb=[0.0] * n,
        ub=[1.0] * n if var_type == "B" else [cplex.infinity] * n,
        types=[var_type] * n,
    )


def add_constraint(model, coeff, vars, rhs, sense, constraint_name=None):
    kwargs = {
        "lin_expr": [cplex.SparsePair(vars, coeff)],
        "senses": [sense], "rhs": [rhs],
    }
    if constraint_name:
        kwargs["names"] = [constraint_name]
    model.linear_constraints.add(**kwargs)


def add_constraint_set(
    model, coeff, vars, rhs, sense, added_constraints,
    constraint_name=None, disable_duplicate_constraint_check=False,
):
    filtered = [(c, v) for c, v in zip(coeff, vars) if c != 0]
    coeff, vars = zip(*filtered) if filtered else ((), ())
    signature = (tuple(coeff), tuple(vars), rhs, sense)
    if signature in added_constraints and not disable_duplicate_constraint_check:
        return
    if vars:
        add_constraint(model, coeff, vars, rhs, sense, constraint_name)
        added_constraints.add(signature)
