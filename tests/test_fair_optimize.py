import numpy as np
import pytest

from src.fair_optimize import build_neighbourhoods, fair_greedy


def _setup(demand_xy, cand_xy, radius=300.0):
    return build_neighbourhoods(demand_xy, cand_xy, np.full(len(cand_xy), radius))


@pytest.mark.unit
def test_neighbourhoods_hold_distances_within_radius():
    demand = np.array([[0.0, 0.0], [100.0, 0.0], [1000.0, 0.0]])
    hoods = _setup(demand, np.array([[0.0, 0.0]]), radius=150.0)

    assert sorted(hoods.idx.tolist()) == [0, 1]
    assert sorted(hoods.dist.tolist()) == pytest.approx([0.0, 100.0])


@pytest.mark.unit
def test_unconstrained_greedy_prefers_more_people_with_same_need():
    demand = np.array([[0.0, 0.0], [5000.0, 0.0]])
    risk = np.array([10.0, 1.0])
    t_ems = np.array([10.0, 10.0])
    cands = demand.copy()

    picks = fair_greedy(risk, t_ems, np.array([0, 0]), _setup(demand, cands), k=2, shares=None)

    assert [p.candidate for p in picks] == [0, 1]


@pytest.mark.unit
def test_quota_keeps_every_prefix_proportional_to_shares():
    demand = np.array([[i * 2000.0, 0.0] for i in range(8)])
    risk = np.array([100.0, 90.0, 80.0, 70.0, 1.0, 1.0, 1.0, 1.0])
    t_ems = np.full(8, 10.0)
    cls = np.array([0, 0, 0, 0, 1, 1, 1, 1])

    picks = fair_greedy(risk, t_ems, cls, _setup(demand, demand), k=4, shares=np.array([0.5, 0.5]))

    assert [p.klasse for p in picks].count(1) == 2
    assert [p.klasse for p in picks][:2] in ([0, 1], [1, 0])


@pytest.mark.unit
def test_gain_counts_only_improvement_over_current_time():
    demand = np.array([[0.0, 0.0]])
    risk = np.array([1.0])
    already_fast = np.array([2.0])

    picks = fair_greedy(risk, already_fast, np.array([0]), _setup(demand, demand), k=1, shares=None)

    assert picks == []


@pytest.mark.unit
def test_greedy_does_not_mutate_current_times():
    demand = np.array([[0.0, 0.0]])
    cur = np.array([10.0])

    fair_greedy(np.array([1.0]), cur, np.array([0]), _setup(demand, demand), k=1, shares=None)

    assert cur[0] == 10.0
