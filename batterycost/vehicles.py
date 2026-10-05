"""Exposure of real EV models to battery-metal prices, rolled up by automaker.

Sales are from the Kelley Blue Book Q4 2025 EV sales report. Pack sizes and chemistry shares are
compiled by hand from public specifications and are the least certain inputs in this project.
"""
import pandas as pd
from . import ASSUMPTIONS
from .bom import DRIVERS
from .cost import exposure_table

SHARES = {"share_NCA": "NCA", "share_NMC811": "NMC811", "share_NMC622": "NMC622", "share_LFP": "LFP"}
US_EV_SALES_2025 = 1_275_930          # Kelley Blue Book total, for coverage


def load_vehicles():
    v = pd.read_csv(ASSUMPTIONS / "vehicles.csv")
    if not ((v[list(SHARES)].sum(axis=1) - 1).abs() < 1e-9).all():
        raise ValueError("chemistry shares must sum to 1 for every row")
    return v


def per_vehicle(prices):
    """For each row: kg of each driver per vehicle, and its dollar value at the latest and year-ago prices."""
    v, exp = load_vehicles(), exposure_table()
    kg = sum(v[s].to_numpy()[:, None] * exp.loc[c, DRIVERS].to_numpy()[None, :] for s, c in SHARES.items()) * v.pack_kwh.to_numpy()[:, None]
    out = pd.concat([v[["row", "automaker", "sales_2025", "pack_kwh", "spec_confidence"]],
                     pd.DataFrame(kg, columns=[f"kg_{d}" for d in DRIVERS])], axis=1)
    now, ago = prices.iloc[-1], prices.iloc[-13]
    out["metal_cost_now"] = kg @ now[DRIVERS].to_numpy()
    out["metal_cost_year_ago"] = kg @ ago[DRIVERS].to_numpy()
    out["change_vs_year_ago"] = out.metal_cost_now - out.metal_cost_year_ago
    for d in ("lithium_carbonate", "nickel", "cobalt"):
        out[f"usd_per_10pct_{d}"] = out[f"kg_{d}"] * now[d] * 0.10
    out["lfp_share"] = v.share_LFP
    return out


def by_automaker(pv):
    """Sales-weighted exposure per vehicle and total across 2025 US sales."""
    w = lambda g, col: (g[col] * g.sales_2025).sum() / g.sales_2025.sum()
    rows = []
    for a, g in pv.groupby("automaker"):
        rows.append({"automaker": a, "sales_2025": int(g.sales_2025.sum()), "avg_pack_kwh": w(g, "pack_kwh"),
                     "lfp_share_of_kwh": (g.lfp_share * g.pack_kwh * g.sales_2025).sum() / (g.pack_kwh * g.sales_2025).sum(),
                     "metal_cost_per_vehicle": w(g, "metal_cost_now"),
                     "change_per_vehicle": w(g, "change_vs_year_ago"),
                     "annual_change_usd": float((g.change_vs_year_ago * g.sales_2025).sum()),
                     "usd_per_10pct_lithium": w(g, "usd_per_10pct_lithium_carbonate"),
                     "usd_per_10pct_nickel": w(g, "usd_per_10pct_nickel"),
                     "usd_per_10pct_cobalt": w(g, "usd_per_10pct_cobalt")})
    return pd.DataFrame(rows).sort_values("change_per_vehicle", ascending=False).reset_index(drop=True)
