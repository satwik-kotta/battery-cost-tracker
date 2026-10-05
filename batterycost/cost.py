"""Cell and pack cost from the bill of materials and market prices.

Cost is linear in the six driver prices, so every month's cost, every attribution and every
contract coefficient comes from the same few numbers: kg of each driver per kWh, plus fixed costs.
"""
import numpy as np, pandas as pd
from . import load
from .bom import cell_bom, chemistries, mass_fractions, DRIVERS
from .prices import drivers as load_drivers, LI2CO3_LI_FRACTION


def _cathode_metal_cost(cathode, price_row):
    """USD of market-priced inputs in 1 kg of cathode active material (no yield loss, with lithium excess)."""
    ch, des = load("chemistries"), load("cell_design")["defaults"]
    f = mass_fractions(ch["cathodes"][cathode]["formula"])
    lce = f.get("Li", 0) * des["lithium_excess"] / LI2CO3_LI_FRACTION
    return (lce * price_row["lithium_carbonate"] + f.get("Ni", 0) * price_row["nickel"] + f.get("Co", 0) * price_row["cobalt"]
            + f.get("Mn", 0) * price_row["manganese"] + f.get("Al", 0) * price_row["aluminium"])


def cathode_adders(prices):
    """Processing adder per kg of cathode, calibrated once to a published cathode price."""
    cfg, out = load("prices")["cathode_processing_usd_kg"], {}
    for cat, c in cfg.items():
        if "calibrate_to" in c:
            p = str(c["calibrate_to"]["period"])
            row = prices[prices.index.year == int(p)].mean() if len(p) == 4 else prices.loc[pd.Period(p, "M")]
            out[cat] = c["calibrate_to"]["usd_kg"] - _cathode_metal_cost(cat, row)
    for cat, c in cfg.items():
        if "same_as" in c:
            out[cat] = out[c["same_as"]]
        if "fixed_price_usd_kg" in c:
            out[cat] = c["fixed_price_usd_kg"]       # whole price is fixed: no market-priced content
    return out


def cathode_price(cathode, prices, adders):
    cell_chem = cathode
    if load("prices")["cathode_processing_usd_kg"][cathode].get("fixed_price_usd_kg"):
        return pd.Series(adders[cathode], index=prices.index)
    return prices.apply(lambda r: _cathode_metal_cost(cell_chem, r), axis=1) + adders[cathode]


def fixed_costs(chem, region, adders, bom=None):
    """USD per kWh that does not move with the six driver prices, itemised."""
    b, om, reg = bom or cell_bom(chem), load("prices")["other_materials_usd_kg"], load("regions")[region]
    q = b["quantities"]
    anode_price = om["graphite"]["value"] if b["anode"] == "graphite" else om["hard_carbon"]["value"]
    if b["lithium_cell"]:
        electrolyte = q["electrolyte_salt"] * om["lipf6_conversion"]["value"] + (q["electrolyte"] - q["electrolyte_salt"]) * om["electrolyte_solvent"]["value"]
    else:
        electrolyte = q["electrolyte"] * om["sodium_electrolyte"]["value"]
    return {"cathode_processing": q["cathode_active"] * adders[load("cell_design")["cells"][chem]["cathode"]],
            "anode": q["anode_active"] * anode_price,
            "binder_and_carbon": q["binder_and_carbon"] * om["binder_and_carbon"]["value"],
            "electrolyte_non_lithium": electrolyte,
            "separator": q["separator_m2"] * reg["separator_usd_m2"],
            "foil_rolling": q["copper_foil"] * om["copper_foil_premium"]["value"] + q["aluminium_foil"] * om["aluminium_foil_premium"]["value"],
            "housing_and_other": reg["housing_and_other_usd_kwh"],
            "manufacturing": reg["manufacturing_usd_kwh"][chem]}


def exposure_table():
    """kg of each market-priced driver per kWh, by chemistry. These are also the contract coefficients:
    a move of $1/kg in a driver moves cell cost by this many dollars per kWh."""
    return pd.DataFrame({c: cell_bom(c)["exposure"] for c in chemistries()}).T[DRIVERS]


def cost_history(region="China", prices=None):
    """Monthly cell cost per kWh by chemistry, split into each driver's contribution and fixed costs."""
    prices = load_drivers()[0] if prices is None else prices
    adders, exp = cathode_adders(prices), exposure_table()
    frames = {}
    for chem in chemistries():
        market = prices[DRIVERS] * exp.loc[chem]
        fixed = fixed_costs(chem, region, adders)
        df = market.copy()
        df["materials_fixed"] = sum(v for k, v in fixed.items() if k != "manufacturing")
        df["manufacturing"] = fixed["manufacturing"]
        df["market_priced"] = market.sum(axis=1)
        df["cell_cost"] = df["market_priced"] + df["materials_fixed"] + df["manufacturing"]
        df["pack_cost"] = df["cell_cost"] + load("regions")["pack_integration_usd_kwh"][chem]
        frames[chem] = df
    return pd.concat(frames, names=["chemistry"])


def attribution(hist, chem, start, end):
    """Exact split of the change in cell cost between two months into each driver's contribution."""
    a, b = hist.loc[(chem, pd.Period(start, "M"))], hist.loc[(chem, pd.Period(end, "M"))]
    d = (b[DRIVERS] - a[DRIVERS]).to_dict()
    d["total"] = float(b.cell_cost - a.cell_cost)
    return d


def breakeven_lithium(region="China", prices=None):
    """Lithium carbonate price (USD per ton) at which a sodium-ion cell costs the same per kWh as LFP,
    holding the other drivers at their latest values."""
    prices = load_drivers()[0] if prices is None else prices
    adders, exp, last = cathode_adders(prices), exposure_table(), prices.iloc[-1]
    def cost_ex_lithium(chem):
        return sum(exp.loc[chem, d] * last[d] for d in DRIVERS if d != "lithium_carbonate") + sum(fixed_costs(chem, region, adders).values())
    gap = cost_ex_lithium("NFPP") - cost_ex_lithium("LFP")
    return float(gap / (exp.loc["LFP", "lithium_carbonate"] - exp.loc["NFPP", "lithium_carbonate"]) * 1000)
