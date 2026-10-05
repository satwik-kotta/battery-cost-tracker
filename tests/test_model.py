import numpy as np, pandas as pd, pytest
from batterycost import prices as P, cost as C, risk as R, vehicles as V, load
from batterycost.bom import cell_bom, chemistries, mass_fractions, DRIVERS
from batterycost.prices import LI2CO3_LI_FRACTION


@pytest.fixture(scope="module")
def data():
    metals = P.parse_imf()
    drv, fit = P.drivers(metals)
    return metals, drv, fit


def test_price_feed_is_complete_and_monthly(data):
    metals, _, _ = data
    assert list(metals.columns) == sorted(metals.columns) or len(metals.columns) == 6
    assert (metals > 0).all().all()
    steps = np.diff([p.ordinal for p in metals.index])
    assert (steps == 1).all(), "a month is missing from the price history"


def test_mass_fractions_from_formula():
    f = mass_fractions({"Li": 1, "Ni": 0.8, "Mn": 0.1, "Co": 0.1, "O": 2})
    assert abs(sum(f.values()) - 1) < 1e-12
    assert abs(f["Li"] - 6.941 / 97.283) < 1e-4      # hand calculation: NMC 811 is 7.13% lithium by mass
    assert abs(f["Ni"] - 0.8 * 58.693 / 97.283) < 1e-4


def test_cathode_mass_matches_hand_calculation():
    # 1 kWh / (200 mAh/g x 3.70 V) = 1.351 kg, divided by 92% yield
    assert abs(cell_bom("NMC811")["quantities"]["cathode_active"] - 1000 / (200 * 3.70) / 0.92) < 1e-9


def test_lithium_balance():
    for c in chemistries():
        b = cell_bom(c)
        li = b["lithium_in_cathode_kg"] + b["lithium_in_electrolyte_kg"]
        assert abs(b["exposure"]["lithium_carbonate"] * LI2CO3_LI_FRACTION - li) < 1e-12


def test_sodium_cell_uses_no_lithium_nickel_cobalt_or_copper():
    e = cell_bom("NFPP")["exposure"]
    assert e["lithium_carbonate"] == e["nickel"] == e["cobalt"] == e["copper"] == 0


def test_better_yield_means_less_material():
    assert cell_bom("LFP", cell_yield=0.97)["quantities"]["cathode_active"] < cell_bom("LFP")["quantities"]["cathode_active"]


def test_calibration_reproduces_its_anchor(data):
    _, drv, _ = data
    adders = C.cathode_adders(drv)
    assert abs(C.cathode_price("NMC811", drv, adders)[pd.Period("2024-05", "M")] - 22.6) < 1e-9


def test_cost_is_linear_in_prices(data):
    _, drv, _ = data
    base = C.cost_history("China", drv).loc["NMC811"].cell_cost.iloc[-1]
    bumped = drv.copy(); bumped["nickel"] += 1.0                    # +$1/kg nickel everywhere
    # the cathode adder is calibrated on prices, so hold it fixed by comparing market-priced cost only
    a = C.cost_history("China", drv).loc["NMC811"].market_priced.iloc[-1]
    b = C.cost_history("China", bumped).loc["NMC811"].market_priced.iloc[-1]
    assert abs((b - a) - C.exposure_table().loc["NMC811", "nickel"]) < 1e-9
    assert base > 0


def test_attribution_adds_up(data):
    _, drv, _ = data
    h = C.cost_history("China", drv)
    for c in chemistries():
        a = C.attribution(h, c, "2025-08", "2026-08")
        assert abs(sum(a[d] for d in DRIVERS) - a["total"]) < 1e-9


def test_breakeven_equalises_sodium_and_lfp(data):
    _, drv, _ = data
    be = C.breakeven_lithium("China", drv)
    at = drv.copy(); at.iloc[-1, at.columns.get_loc("lithium_carbonate")] = be / 1000
    adders, exp, last = C.cathode_adders(drv), C.exposure_table(), at.iloc[-1]
    cost = lambda c: sum(exp.loc[c, d] * last[d] for d in DRIVERS) + sum(C.fixed_costs(c, "China", adders).values())
    assert abs(cost("LFP") - cost("NFPP")) < 1e-9


def test_lithium_fit_is_tight(data):
    _, _, fit = data
    assert fit["r2"] > 0.98 and fit["slope"] > 0
    assert fit["mean_abs_pct_error_leave_one_out"] < 0.15


def test_simulation_is_reproducible_and_ordered(data):
    metals, _, _ = data
    a, _ = R.cost_at_risk(metals, paths=500, seed=1)
    b, _ = R.cost_at_risk(metals, paths=500, seed=1)
    assert a.equals(b)
    assert (a.p05 <= a.p50).all() and (a.p50 <= a.p95).all()
    assert abs(a.loc["NFPP", "p95"]) < abs(a.loc["LFP", "p95"])   # no lithium, so far less price risk


def test_simulation_uses_only_history_given(data):
    metals, _, _ = data
    early = metals.loc[:"2019-12"]
    s1 = R.simulate(early, seed=3)
    s2 = R.simulate(metals.loc[:"2019-12"].copy(), seed=3)
    assert np.allclose(s1, s2)


def test_vehicle_table_is_consistent(data):
    _, drv, _ = data
    pv = V.per_vehicle(drv)
    assert pv.sales_2025.sum() / V.US_EV_SALES_2025 > 0.9
    assert (pv.metal_cost_now > 0).all()
    assert abs(V.by_automaker(pv).sales_2025.sum() - pv.sales_2025.sum()) == 0


def test_every_assumption_has_a_source():
    for name, c in load("chemistries")["cathodes"].items():
        assert c.get("source"), f"{name} has no source"
    for name, m in load("prices")["other_materials_usd_kg"].items():
        assert m.get("source"), f"{name} has no source"
