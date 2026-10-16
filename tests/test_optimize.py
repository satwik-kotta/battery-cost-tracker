import numpy as np, pandas as pd, pytest
from batterycost import prices as P, cost as C, risk as R, load
from batterycost.bom import chemistries
from batterycost.optimize import solve_mix, cvar, stack_mass_per_kwh, density_sweep


@pytest.fixture(scope="module")
def setup():
    metals = P.parse_imf()
    drv, fit = P.drivers(metals)
    chems = chemistries()
    now = C.cost_history("China", drv)["cell_cost"].unstack(0)[chems].iloc[-1].to_numpy()
    cfg = load("optimizer")
    caps = np.array([cfg["share_caps"][c] for c in chems])
    scen = R.cost_scenarios(metals, now, fit, 12, 2000, seed=1)
    return metals, fit, now, caps, scen, stack_mass_per_kwh().loc[chems].to_numpy()


def test_cvar_matches_a_hand_calculation():
    losses = np.arange(1.0, 101.0)                       # 1..100; worst 5% is 96..100
    assert cvar(losses, 0.95) == pytest.approx(98.0)


def test_toy_problem_picks_the_cheaper_asset_when_nothing_else_matters():
    cost = np.array([[10.0, 12.0]] * 50)                 # asset 0 is cheaper in every scenario
    r = solve_mix(cost, mass=[1.0, 1.0], risk_weight=0.5)
    assert r["shares"] == pytest.approx([1.0, 0.0], abs=1e-9)


def test_toy_problem_diversifies_two_offsetting_risks():
    # Two equally priced assets that are expensive in opposite scenarios: the lowest-CVaR mix is 50/50.
    cost = np.array([[10.0, 14.0], [14.0, 10.0]] * 100)
    r = solve_mix(cost, mass=[1.0, 1.0], risk_weight=1.0, alpha=0.9)
    assert r["shares"] == pytest.approx([0.5, 0.5], abs=1e-6)
    assert r["cvar"] == pytest.approx(12.0)


def test_lp_cvar_equals_cvar_of_the_returned_mix(setup):
    _, _, _, caps, scen, mass = setup
    r = solve_mix(scen, mass, 1000 / 280, caps, risk_weight=1.0)
    assert r["cvar"] == pytest.approx(cvar(scen @ r["shares"]), rel=1e-9)
    # no other feasible mix has a lower CVaR: try random mixes that meet the constraints
    rng = np.random.default_rng(0)
    for _ in range(300):
        x = rng.dirichlet(np.ones(len(mass)))
        if (x <= caps + 1e-12).all() and mass @ x <= 1000 / 280:
            assert cvar(scen @ x) >= r["cvar"] - 1e-6


def test_constraints_hold(setup):
    _, _, _, caps, scen, mass = setup
    r = solve_mix(scen, mass, 1000 / 280, caps, risk_weight=0.5)
    x = r["shares"]
    assert x.sum() == pytest.approx(1.0)
    assert (x >= -1e-12).all() and (x <= caps + 1e-9).all()
    assert mass @ x <= 1000 / 280 + 1e-9


def test_tighter_density_requirement_never_lowers_cost(setup):
    _, _, _, caps, scen, mass = setup
    sweep = density_sweep(scen, mass, caps, [220, 250, 280, 310], 0.5)
    assert (sweep.expected_cost.diff().dropna() >= -1e-9).all()
    assert (sweep.cvar95_cost.diff().dropna() >= -1e-9).all()
    assert sweep.stack_wh_per_kg.round(6).ge(sweep.min_wh_per_kg - 1e-6).all()


def test_infeasible_requirement_raises(setup):
    _, _, _, caps, scen, mass = setup
    with pytest.raises(ValueError):
        solve_mix(scen, mass, 1000 / 400, caps)           # no chemistry reaches 400 Wh/kg


def test_scenarios_use_only_the_history_they_are_given(setup):
    metals, fit, now, caps, _, mass = setup
    origin = metals.iloc[:100]
    altered = metals.copy()
    altered.iloc[100:] = altered.iloc[100:] * 3.0         # change every price after the origin
    a = R.cost_scenarios(origin, now, fit, 12, 500, seed=7)
    b = R.cost_scenarios(altered.iloc[:100], now, fit, 12, 500, seed=7)
    assert np.array_equal(a, b)                            # future prices cannot reach the scenarios


def test_stack_mass_ranks_chemistries_as_expected():
    m = stack_mass_per_kwh()
    assert m["NMC811"] < m["LFP"] < m["NFPP"]              # nickel cells are lightest, sodium-ion heaviest
    assert 1000 / m["NMC811"] == pytest.approx(321.1, abs=0.5)
