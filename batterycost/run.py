"""Run the whole tracker: prices -> bill of materials -> cost history -> validation -> risk -> vehicles.

Usage: python -m batterycost.run [--refresh] [--out outputs]
  --refresh  download the latest IMF prices first (needs internet access to api.imf.org)
"""
import argparse, json, pathlib
import numpy as np, pandas as pd
from . import load, prices as P, cost as C, risk as R, vehicles as V
from .bom import cell_bom, chemistries, DRIVERS

SENSITIVITY = {"cell_yield": ("Cell yield", 0.87, 0.97), "q_mAh_g": ("Cathode capacity", -0.05, 0.05),
               "v_cell": ("Cell voltage", -0.03, 0.03), "lithium_excess": ("Lithium excess", 1.00, 1.06),
               "np_ratio": ("Anode/cathode ratio", 1.05, 1.15), "areal_capacity_mAh_cm2": ("Electrode loading", -0.15, 0.15),
               "electrolyte_g_per_Ah": ("Electrolyte loading", -0.20, 0.20)}


def _period_mean(series, period):
    p = str(period)
    return float(series[series.index.year == int(p)].mean() if len(p) == 4 else series[pd.Period(p, "M")])


def validation(drv, hist):
    cfg, bench, adders = load("prices"), load("benchmarks"), C.cathode_adders(drv)
    rows = []
    for c in cfg["out_of_sample_checks"]:
        m = _period_mean(C.cathode_price(c["cathode"], drv, adders), c["period"])
        rows.append({"check": f"{c['cathode']} cathode price, {c['period']} (USD/kg)", "model": m, "published_low": c["usd_kg"],
                     "published_high": c["usd_kg"], "source": c["source"], "used_in_calibration": False})
    for b in bench["cell_cost_usd_kwh"]:
        m = float(hist.loc[b["chemistry"]].loc[b["window"][0]:b["window"][1]].cell_cost.mean())
        rows.append({"check": f"{b['chemistry']} cell cost, China, {b['window'][0]} to {b['window'][1]} (USD/kWh)", "model": m,
                     "published_low": b["low"], "published_high": b["high"], "source": b["source"], "used_in_calibration": False})
    for b in bench["pack_price_usd_kwh"]:
        m = float(hist.loc[b["chemistry"]].loc["2025-01":"2025-12"].pack_cost.mean())
        rows.append({"check": f"{b['chemistry']} pack, 2025: model cost vs market price (USD/kWh)", "model": m,
                     "published_low": b["value"], "published_high": b["value"], "source": b["source"], "used_in_calibration": False})
    v = pd.DataFrame(rows)
    mid = (v.published_low + v.published_high) / 2
    v["gap_pct"] = v.model / mid - 1
    return v


def sensitivity(chem, drv, region="China"):
    """Change in latest cell cost when one design input moves across a plausible range."""
    des, ch = load("cell_design"), load("chemistries")
    base_inputs = {**des["defaults"], **des["cells"][chem], **ch["cathodes"][des["cells"][chem]["cathode"]]}
    adders, last = C.cathode_adders(drv), drv.iloc[-1]

    def cell_cost(**o):
        b = cell_bom(chem, **o)
        market = sum(b["exposure"][d] * last[d] for d in DRIVERS)
        return market + sum(C.fixed_costs(chem, region, adders, bom=b).values())
    base, rows = cell_cost(), []
    for key, (label, lo, hi) in SENSITIVITY.items():
        v0 = base_inputs[key]
        lo_v, hi_v = (v0 * (1 + lo), v0 * (1 + hi)) if lo < 0 else (lo, hi)
        rows.append({"chemistry": chem, "input": label, "low_value": lo_v, "high_value": hi_v,
                     "cost_at_low": cell_cost(**{key: lo_v}) - base, "cost_at_high": cell_cost(**{key: hi_v}) - base})
    return pd.DataFrame(rows), base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--out", default="outputs")
    a = ap.parse_args()
    out = pathlib.Path(a.out); out.mkdir(exist_ok=True)
    if a.refresh:
        P.fetch_imf()
    metals = P.parse_imf()
    drv, fit = P.drivers(metals)
    latest, year_ago = drv.index[-1], drv.index[-13]

    pd.concat([metals.add_suffix("_usd_t"), drv.add_suffix("_usd_kg")], axis=1).round(3).to_csv(out / "prices_monthly.csv")
    bom_rows = []
    for c in chemistries():
        b = cell_bom(c)
        bom_rows.append({"chemistry": c, **{f"{k}_per_kwh": v for k, v in b["quantities"].items()},
                         **{f"cathode_{k}_kg_per_kwh": v for k, v in b["cathode_elements"].items()},
                         **{f"exposure_{k}_kg_per_kwh": v for k, v in b["exposure"].items()}})
    pd.DataFrame(bom_rows).round(4).to_csv(out / "bill_of_materials.csv", index=False)

    hist = {r: C.cost_history(r, drv) for r in ("China", "United States")}
    for r, h in hist.items():
        h.round(3).to_csv(out / f"cost_history_{r.lower().replace(' ', '_')}.csv")
    h = hist["China"]
    val = validation(drv, h); val.round(3).to_csv(out / "validation.csv", index=False)

    exp = C.exposure_table()
    coef = exp.copy(); coef.index.name = "chemistry"
    per10 = (exp * drv.iloc[-1][DRIVERS] * 0.10).add_prefix("usd_kwh_per_10pct_")
    pd.concat([coef.add_prefix("usd_kwh_per_usd_kg_"), per10], axis=1).round(4).to_csv(out / "contract_coefficients.csv", index_label="chemistry")

    attr = {c: C.attribution(h, c, str(year_ago), str(latest)) for c in chemistries()}
    trough = {c: str(h.loc[c].loc["2023-01":].cell_cost.idxmin()) for c in chemistries()}

    car, _ = R.cost_at_risk(metals)
    car_plain, _ = R.cost_at_risk(metals, vol_adjust=False)
    car.round(3).to_csv(out / "cost_at_risk.csv", index_label="chemistry")
    bt, cov = R.backtest(metals)
    _, cov_plain = R.backtest(metals, vol_adjust=False)
    bt.round(3).to_csv(out / "risk_backtest.csv", index=False)

    be = C.breakeven_lithium("China", drv)
    gap = (h.loc["LFP"].cell_cost - h.loc["NFPP"].cell_cost)
    sens = pd.concat([sensitivity(c, drv)[0] for c in ("NMC811", "LFP")]); sens.round(3).to_csv(out / "design_sensitivity.csv", index=False)

    pv = V.per_vehicle(drv); pv.round(2).to_csv(out / "vehicle_exposure.csv", index=False)
    am = V.by_automaker(pv); am.round(2).to_csv(out / "automaker_exposure.csv", index=False)

    latest_cost = {c: {k: float(h.loc[c].iloc[-1][k]) for k in ["cell_cost", "pack_cost", "market_priced", "materials_fixed", "manufacturing"] + DRIVERS} for c in chemistries()}
    summary = {
        "latest_month": str(latest), "year_ago_month": str(year_ago), "first_month": str(drv.index[0]), "months": int(len(drv)),
        "lithium_fit": fit,
        "prices_latest": drv.iloc[-1].to_dict(), "prices_year_ago": drv.iloc[-13].to_dict(),
        "price_change_yoy": (drv.iloc[-1] / drv.iloc[-13] - 1).to_dict(),
        "cathode_adders_usd_kg": {k: float(v) for k, v in C.cathode_adders(drv).items()},
        "latest_cost_china": latest_cost,
        "latest_cell_cost_us": {c: float(hist["United States"].loc[c].iloc[-1].cell_cost) for c in chemistries()},
        "cell_cost_year_ago_china": {c: float(h.loc[c].iloc[-13].cell_cost) for c in chemistries()},
        "attribution_yoy": attr, "trough_month_since_2023": trough,
        "cost_at_risk": car.to_dict("index"),
        "backtest": {"origins": int(bt.origin.nunique()), "first_origin": bt.origin.min(), "last_origin": bt.origin.max(), "nominal": 0.90,
                     "coverage_vol_adjusted": cov.to_dict(), "coverage_plain": cov_plain.to_dict(),
                     "p95_plain": car_plain.p95.to_dict()},
        "sodium_breakeven_lithium_carbonate_usd_t": be,
        "sodium_cheaper_now": bool(gap.iloc[-1] > 0), "lfp_minus_sodium_latest": float(gap.iloc[-1]),
        "sodium_cheaper_share_of_months": float((gap > 0).mean()),
        "vehicle_sales_coverage": float(pv.sales_2025.sum() / V.US_EV_SALES_2025),
        "total_annual_change_usd": float(am.annual_change_usd.sum()),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    pd.set_option("display.width", 220); pd.set_option("display.max_columns", 20)
    print(f"Prices through {latest}. Lithium fit R2 {fit['r2']:.3f}, leave-one-out error {fit['mean_abs_pct_error_leave_one_out']:.1%}")
    print(pd.DataFrame(latest_cost).T[["cell_cost", "pack_cost", "market_priced"]].round(1))
    print(val[["check", "model", "published_low", "published_high", "gap_pct"]].round(2).to_string(index=False))
    print(car.round(1)); print("backtest coverage (nominal 90%):", cov.round(2).to_dict(), "plain:", cov_plain.round(2).to_dict())
    print(f"Sodium-ion = LFP at lithium carbonate ${be:,.0f}/t; latest estimate ${drv.iloc[-1].lithium_carbonate*1000:,.0f}/t")
    print(sens.round(2).to_string(index=False)); print(am.round(0).to_string(index=False))


if __name__ == "__main__":
    main()
