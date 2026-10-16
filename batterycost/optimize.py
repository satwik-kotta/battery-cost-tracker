"""Chemistry mix optimiser: what share of cell volume to buy in each chemistry for the lowest cost at an acceptable risk.

The decision: split one kWh of cell purchases across the five chemistries. The price simulation in risk.py gives
thousands of joint 12-month price scenarios, hence thousands of cost outcomes per chemistry. The optimiser picks the mix
that minimises (1 - lambda) x expected cost + lambda x CVaR, the average cost in the worst 5% of scenarios, subject to
  * shares add to 1 and no chemistry exceeds its supply cap, and
  * the fleet meets a minimum energy density.
CVaR is minimised exactly as a linear program (Rockafellar and Uryasev, 2000), solved with HiGHS through SciPy.

Energy density here is a stack proxy: kWh per kg of cathode, anode, binder, electrolyte and foil. It leaves out the
separator, housing and tabs, so it is higher than a finished cell's. It is used only to rank chemistries against each other.
Mass per kWh is linear in the mix, which is why the requirement can be a linear constraint.

Usage: python -m batterycost.optimize [--out outputs] [--skip-backtest]
"""
import argparse, json, pathlib
import numpy as np, pandas as pd
from scipy.optimize import linprog
from scipy.sparse import csr_matrix, hstack, vstack, identity, lil_matrix
from . import load, prices as P, cost as C, risk as R
from .bom import cell_bom, chemistries

STACK_PARTS = ("cathode_active", "anode_active", "binder_and_carbon", "electrolyte", "copper_foil", "aluminium_foil")


def stack_mass_per_kwh():
    """kg of stack materials per kWh of cell energy, by chemistry, with no yield loss."""
    return pd.Series({c: sum(cell_bom(c, cell_yield=1.0)["quantities"][k] for k in STACK_PARTS) for c in chemistries()})


def cvar(losses, alpha=0.95):
    """Average of the worst (1 - alpha) share of outcomes."""
    k = max(1, int(round((1 - alpha) * len(losses))))
    return float(np.sort(losses)[-k:].mean())


def solve_mix(cost, mass, max_mass=None, caps=None, risk_weight=0.5, alpha=0.95):
    """Best mix of chemistries for a set of cost scenarios.

    cost: scenarios x chemistries, USD per kWh. mass: kg per kWh by chemistry (same order).
    max_mass: ceiling on the mix's average kg per kWh (the energy density requirement); None for no requirement.
    caps: largest share per chemistry; None for no cap. Returns shares, expected cost, CVaR and the shadow price of mass.
    Raises ValueError if no mix meets the constraints.
    """
    cost = np.atleast_2d(np.asarray(cost, dtype=float))
    S, K = cost.shape
    mass = np.asarray(mass, dtype=float)
    lam = float(risk_weight)
    c_obj = np.concatenate([(1 - lam) * cost.mean(axis=0), [lam], np.full(S, lam / ((1 - alpha) * S))])

    rows = []
    if max_mass is not None:                                           # row 0: mass requirement
        m = lil_matrix((1, K + 1 + S)); m[0, :K] = mass
        rows.append(csr_matrix(m))
    cvar_rows = hstack([csr_matrix(cost), csr_matrix(-np.ones((S, 1))), -identity(S, format="csr")], format="csr")
    rows.append(cvar_rows)                                              # loss_s - eta <= u_s
    A_ub = vstack(rows, format="csr")
    b_ub = np.concatenate([[max_mass] if max_mass is not None else [], np.zeros(S)])
    A_eq = csr_matrix(np.concatenate([np.ones(K), [0.0], np.zeros(S)])[None, :])
    cap = np.ones(K) if caps is None else np.asarray(caps, dtype=float)
    bounds = [(0.0, float(cap[k])) for k in range(K)] + [(None, None)] + [(0.0, None)] * S

    res = linprog(c_obj, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=[1.0], bounds=bounds, method="highs")
    if res.status != 0:
        raise ValueError(f"no feasible mix: {res.message}")
    x = np.clip(res.x[:K], 0.0, None); x = x / x.sum()
    losses = cost @ x
    return {"shares": x, "expected": float(losses.mean()), "cvar": cvar(losses, alpha),
            "mass": float(mass @ x), "objective": float(res.fun),
            "mass_shadow_price": float(res.ineqlin.marginals[0]) if max_mass is not None else 0.0}


def _settings(cfg=None):
    cfg = cfg or load("optimizer")
    chems = chemistries()
    caps = np.array([cfg["share_caps"][c] for c in chems])
    return cfg, chems, caps


def _row(label, r, chems, mass, extra=None):
    return {**(extra or {}), "case": label, **{f"share_{c}": r["shares"][i] for i, c in enumerate(chems)},
            "expected_cost": r["expected"], "cvar95_cost": r["cvar"], "avg_kg_per_kwh": r["mass"],
            "stack_wh_per_kg": 1000 / r["mass"]}


def density_sweep(cost, mass, caps, e_grid, lam, alpha=0.95):
    """What each extra Wh/kg of required energy density costs, at a fixed risk weight."""
    chems = chemistries()
    rows = []
    for e in e_grid:
        r = solve_mix(cost, mass, 1000 / e, caps, lam, alpha)
        rows.append(_row(f"{e} Wh/kg", r, chems, mass, {"min_wh_per_kg": e, "shadow_usd_kwh_per_kg": r["mass_shadow_price"]}))
    return pd.DataFrame(rows)


def sensitivity(cost, mass, cfg):
    """How the recommended mix moves when each assumption is changed on its own."""
    cfg, chems, caps = _settings(cfg)
    lam, e0, nf = cfg["objective"]["risk_weight"], cfg["requirements"]["min_stack_energy_density_wh_kg"], cfg["share_caps"]["NFPP"]
    cases = [("Base case", lam, e0, nf)]
    cases += [(f"Sodium-ion cap {v:.0%}", lam, e0, v) for v in (0.0, 0.15, 0.50, 1.0) if v != nf]
    cases += [(f"Risk weight {v}", v, e0, nf) for v in (0.0, 0.25, 0.75, 1.0) if v != lam]
    cases += [(f"Energy density {v} Wh/kg", lam, v, nf) for v in (240, 260, 300, 310) if v != e0]
    rows = []
    for label, l, e, cap in cases:
        cp = caps.copy(); cp[chems.index("NFPP")] = cap
        r = solve_mix(cost, mass, 1000 / e, cp, l, cfg["objective"]["cvar_level"])
        rows.append(_row(label, r, chems, mass))
    return pd.DataFrame(rows)


def backtest(metals, drv, cfg=None):
    """Would the optimiser have helped? At each past month, optimise using only the data up to then,
    hold the mix for 12 months, and price it at the cell costs that actually followed.

    As in risk.backtest, the lithium price mapping is fit once on the full anchor set, so this tests the simulation
    and the optimiser, not the mapping. Monthly origins overlap, so the effective number of independent 12-month
    windows is about the number of origins divided by 12.
    """
    cfg, chems, caps = _settings(cfg)
    obj = cfg["objective"]
    horizon, alpha, lam = obj["horizon_months"], obj["cvar_level"], obj["risk_weight"]
    mass = stack_mass_per_kwh().loc[chems].to_numpy()
    max_mass = 1000 / cfg["requirements"]["min_stack_energy_density_wh_kg"]
    fit = P.fit_lithium_carbonate(metals)[1]
    hist_cost = C.cost_history("China", drv)["cell_cost"].unstack(0)[chems]      # month x chemistry
    months = metals.index
    first = months.get_loc(pd.Period(cfg["backtest"]["first_origin"], "M"))
    fixed = {"All NCA": "NCA", "All NMC 811": "NMC811"}
    rows = []
    for i in range(first, len(months) - horizon):
        now_cost = hist_cost.loc[months[i]].to_numpy()
        future = hist_cost.loc[months[i + horizon]].to_numpy()
        scen = R.cost_scenarios(metals.iloc[: i + 1], now_cost, fit, horizon, cfg["backtest"]["paths"], seed=i)
        plans = {
            "Risk aware optimiser": solve_mix(scen, mass, max_mass, caps, lam, alpha)["shares"],
            "Expected cost optimiser": solve_mix(scen, mass, max_mass, caps, 0.0, alpha)["shares"],
            "Cheapest today": solve_mix(now_cost[None, :], mass, max_mass, caps, 0.0, alpha)["shares"],
        }
        for label, chem in fixed.items():
            plans[label] = np.eye(len(chems))[chems.index(chem)]
        for label, x in plans.items():
            rows.append({"origin": str(months[i]), "strategy": label, "cost_at_origin": float(now_cost @ x),
                         "realized_cost_12m": float(future @ x), **{f"share_{c}": x[k] for k, c in enumerate(chems)}})
    bt = pd.DataFrame(rows)
    return bt, backtest_summary(bt)


def backtest_summary(bt):
    base = bt[bt.strategy == "Cheapest today"].set_index("origin").realized_cost_12m
    out = []
    for s, g in bt.groupby("strategy", sort=False):
        g = g.set_index("origin")
        diff = g.realized_cost_12m - base.reindex(g.index)
        out.append({"strategy": s, "origins": len(g), "mean_realized_cost": g.realized_cost_12m.mean(),
                    "p95_realized_cost": g.realized_cost_12m.quantile(0.95), "worst_realized_cost": g.realized_cost_12m.max(),
                    "mean_vs_cheapest_today": diff.mean(), "p95_vs_cheapest_today": diff.quantile(0.95),
                    "worst_vs_cheapest_today": diff.max(), "share_of_origins_cheaper": float((diff < -1e-9).mean()),
                    "mean_share_NFPP": g["share_NFPP"].mean()})
    return pd.DataFrame(out)


def plots(sweep, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    chems = chemistries()
    fig, ax = plt.subplots(1, 2, figsize=(11, 4))
    ax[0].plot(sweep.min_wh_per_kg, sweep.cvar95_cost, "o-", color="#b03a2e", label="CVaR 95% (worst 5% of outcomes)")
    ax[0].plot(sweep.min_wh_per_kg, sweep.expected_cost, "o-", color="#1a4fa0", label="Expected")
    ax[0].set_xlabel("Minimum stack energy density (Wh/kg)"); ax[0].set_ylabel("Cell cost in 12 months (USD/kWh)")
    ax[0].set_title("What energy density costs"); ax[0].legend(fontsize=8)
    ax[1].stackplot(sweep.min_wh_per_kg, *[sweep[f"share_{c}"] for c in chems], labels=chems)
    ax[1].set_xlabel("Minimum stack energy density (Wh/kg)"); ax[1].set_ylabel("Share of kWh bought")
    ax[1].set_title("Cheapest mix at each requirement"); ax[1].legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), fontsize=8, ncol=5, frameon=False)
    ax[1].set_xlim(sweep.min_wh_per_kg.min(), sweep.min_wh_per_kg.max()); ax[1].set_ylim(0, 1)
    fig.tight_layout(); fig.savefig(out / "optimizer_density.png", dpi=150); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="outputs")
    ap.add_argument("--skip-backtest", action="store_true")
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(exist_ok=True)
    cfg, chems, caps = _settings()
    obj, e0 = cfg["objective"], cfg["requirements"]["min_stack_energy_density_wh_kg"]

    metals = P.parse_imf(); drv, fit = P.drivers(metals)
    now = C.cost_history("China", drv)["cell_cost"].unstack(0)[chems].iloc[-1]
    scen = R.cost_scenarios(metals, now.to_numpy(), P.fit_lithium_carbonate(metals)[1], obj["horizon_months"],
                            cfg["simulation"]["paths"], seed=cfg["simulation"]["seed"])
    mass = stack_mass_per_kwh().loc[chems].to_numpy()

    base = solve_mix(scen, mass, 1000 / e0, caps, obj["risk_weight"], obj["cvar_level"])
    sweep = density_sweep(scen, mass, caps, list(range(200, 321, 10)), obj["risk_weight"], obj["cvar_level"])
    sens = sensitivity(scen, mass, cfg)
    single = pd.DataFrame([{"chemistry": c, "stack_kg_per_kwh": mass[i], "stack_wh_per_kg": 1000 / mass[i], "cost_now": now[c],
                            "expected_cost_12m": scen[:, i].mean(), "cvar95_cost_12m": cvar(scen[:, i], obj["cvar_level"])}
                           for i, c in enumerate(chems)])
    single.round(3).to_csv(out / "optimizer_chemistries.csv", index=False)
    sweep.round(4).to_csv(out / "optimizer_density_sweep.csv", index=False)
    sens.round(4).to_csv(out / "optimizer_sensitivity.csv", index=False)
    plots(sweep, out)

    summary = {"as_of": str(drv.index[-1]), "risk_weight": obj["risk_weight"], "cvar_level": obj["cvar_level"],
               "min_stack_wh_per_kg": e0, "paths": cfg["simulation"]["paths"],
               "recommended_mix": {c: float(base["shares"][i]) for i, c in enumerate(chems)},
               "expected_cost": base["expected"], "cvar95_cost": base["cvar"], "stack_wh_per_kg": 1000 / base["mass"],
               "mass_shadow_price_usd_kwh_per_kg": base["mass_shadow_price"],
               "single_chemistry_nca": {"expected": float(scen[:, chems.index("NCA")].mean()), "cvar95": cvar(scen[:, chems.index("NCA")], obj["cvar_level"])}}
    if not a.skip_backtest:
        bt, bs = backtest(metals, drv, cfg)
        bt.round(4).to_csv(out / "optimizer_backtest.csv", index=False)
        bs.round(3).to_csv(out / "optimizer_backtest_summary.csv", index=False)
        summary["backtest"] = bs.round(3).to_dict("records")
    (out / "optimizer_summary.json").write_text(json.dumps(summary, indent=2))

    pd.set_option("display.width", 220); pd.set_option("display.max_columns", 30)
    print(single.round(2).to_string(index=False))
    print(f"\nRecommended mix at {e0} Wh/kg, risk weight {obj['risk_weight']}:")
    print({c: round(float(base['shares'][i]), 3) for i, c in enumerate(chems)}, f"expected {base['expected']:.2f}, CVaR95 {base['cvar']:.2f}")
    print(sweep[["min_wh_per_kg", "expected_cost", "cvar95_cost", "shadow_usd_kwh_per_kg"] + [f"share_{c}" for c in chems]].round(3).to_string(index=False))
    print(sens[["case", "expected_cost", "cvar95_cost"] + [f"share_{c}" for c in chems]].round(3).to_string(index=False))
    if not a.skip_backtest:
        print(bs.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
