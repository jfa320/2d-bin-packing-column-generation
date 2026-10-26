"""Solver-free checks of the timing/evolution definitions in the final report."""

import pytest

from quadrant_pilot_comparison import EPS, evolution, summarize


def test_observed_improvements_use_full_precision_and_exclude_initial_zero():
    progress = [dict(rmp_solve=i, elapsed_s=t, lp_value=v) for i, t, v in (
        (1, 0.01, 0), (2, 30, 49), (3, 59, 49 + EPS / 4),
        (4, 74, 49.5), (5, 80, 49.5 + EPS / 4), (6, 90, 50),
    )]
    rows = evolution("case", 1200, [], progress)
    assert [r["iteration"] for r in rows if r["improved"]] == [2, 4, 6]
    assert rows[-1]["time_source"] == "observed_completion"
    assert rows[2]["rmp_value"] == 49 + EPS / 4


def test_old_pilot_completion_estimate_includes_solve():
    rows = evolution("case", 60, [dict(iteration="1", rmp_time_limit_s="40.0",
                                       master_solve_time_s="0.2", lp_value="49")])
    assert rows[0]["rmp_completion_s"] == pytest.approx(20.2)
    assert rows[0]["time_source"] == "estimated_from_remaining_budget"


def test_unproven_rmp_remains_diagnostic_and_does_not_count_as_improvement():
    progress = [dict(rmp_solve=1, elapsed_s=20, lp_value=49, proven_optimal=True),
                dict(rmp_solve=2, elapsed_s=1200, lp_value=50, proven_optimal=False)]
    rows = evolution("case", 1200, [], progress)
    assert rows[-1]["rmp_value"] == 50
    assert rows[-1]["rmp_proven_optimal"] is False
    assert rows[-1]["improved"] is False
    assert [r["rmp_value"] for r in rows if r["improved"]] == [49]


def test_summary_does_not_reuse_old_pricing_certificates():
    row = dict(instance="case", time_limit_s="1200", pricing_time_s="1000", total_time_s="1201",
               lp_value="49.5", lp_convergence_proven="False", lp_is_current="True", status="TIMEOUT",
               master_lp_time_s="100", pricing_solve_time_s="700", cg_iterations="2", pricing_calls="5",
               generated_columns="4", duplicates="0", final_columns="8", cg_stop_reason="global_deadline",
               error_message="NA")
    iterations = [dict(iteration="1", master_revision="4"), dict(iteration="2", master_revision="8")]
    prices = [dict(iteration="1", quadrant=str(k), wall_time_s="10", closure_proven="True") for k in range(1,5)]
    prices.append(dict(iteration="2", quadrant="1", wall_time_s="960", closure_proven="False",
                       reduced_cost="0", reduced_cost_upper_bound="0.5", raw_cplex_status="107"))
    progress = [dict(rmp_solve=i, elapsed_s=t, lp_value=v) for i, t, v in ((1,0.1,0),(2,70,49.5))]
    summary, history, tail = summarize(row, iterations, prices, progress)
    assert summary["lp_certified"] == "False"
    assert summary["last_rmp"] == 49.5
    assert summary["rmp_by_60_s"] == 0
    assert summary["improvements_after_60_s"] == 1
    assert summary["last_improvement_iteration"] == 2
    assert summary["last_improvement_time_s"] == 70
    assert summary["q1_time_s"] == 970
    assert summary["q1_percent_pricing"] == 97
    assert [r["executed"] for r in tail] == [True, False, False, False]
    assert tail[0]["reduced_cost_upper_bound"] == "0.5"
    assert all(r["master_revision"] == "8" for r in tail)
    assert all(r["closure_proven"] is None for r in tail[1:])
    assert not any("gap" in key for key in summary)
