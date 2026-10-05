"""Bill of materials per kWh of sellable cell energy, derived from chemistry and cell design."""
from functools import lru_cache
from . import load
from .prices import LI2CO3_LI_FRACTION

DRIVERS = ["lithium_carbonate", "nickel", "cobalt", "manganese", "copper", "aluminium"]
LIPF6_LI_FRACTION = 6.941 / (6.941 + 30.974 + 6 * 18.998)


def mass_fractions(formula):
    """Mass share of each element in a compound, from its formula."""
    m = load("chemistries")["atomic_mass"]
    total = sum(n * m[e] for e, n in formula.items())
    return {e: n * m[e] / total for e, n in formula.items()}


def cell_bom(chem, **overrides):
    """Quantities per kWh of sellable energy for one cell chemistry.

    Returns a dict with physical quantities (kg or m2 per kWh) and `exposure`: kg per kWh of each
    market-priced driver, which is what links the cell to commodity prices.
    `overrides` replaces design inputs (e.g. cell_yield=0.95, q_mAh_g=210) for sensitivity analysis.
    """
    return _cell_bom(chem, tuple(sorted(overrides.items())))


@lru_cache(maxsize=None)
def _cell_bom(chem, overrides):
    ch, des = load("chemistries"), load("cell_design")
    o = dict(overrides)
    d = {**des["defaults"], **des["cells"][chem], **{k: v for k, v in o.items() if k not in ("q_mAh_g", "v_cell")}}
    cat = {**ch["cathodes"][d["cathode"]], **{k: v for k, v in o.items() if k in ("q_mAh_g", "v_cell")}}
    an = ch["anodes"][d["anode"]]
    per_yield = 1 / d["cell_yield"]                       # material bought per unit of good output

    ah = 1000 / cat["v_cell"]                             # Ah per kWh
    cam = 1000 / (cat["q_mAh_g"] * cat["v_cell"])         # kg cathode active material per kWh
    anode = cam * cat["q_mAh_g"] * d["np_ratio"] / an["q_mAh_g"]
    inactive = cam * (1 / d["cathode_active_fraction"] - 1) + anode * (1 / d["anode_active_fraction"] - 1)
    electrolyte = d["electrolyte_g_per_Ah"] * ah / 1000
    coated_m2 = ah / (d["areal_capacity_mAh_cm2"] * 10)   # one-side coated area
    foil_m2 = coated_m2 / 2 * d["foil_overhang"]          # each foil is coated on both sides
    rho = des["density_kg_m3"]
    al_foil = foil_m2 * d["aluminium_foil_um"] * 1e-6 * rho["aluminium"]
    cu_foil = foil_m2 * d["copper_foil_um"] * 1e-6 * rho["copper"]
    if d["anode_collector"] == "aluminium":               # sodium-ion: no copper needed
        al_foil, cu_foil = al_foil * 2, 0.0

    frac = mass_fractions(cat["formula"])
    lithium_cell = cat["lithium_salt"] != "none"
    salt = electrolyte * d["lipf6_weight_fraction"]
    li_cathode = cam * frac.get("Li", 0) * d["lithium_excess"]
    li_electrolyte = salt * LIPF6_LI_FRACTION if lithium_cell else 0.0

    q = {"cathode_active": cam, "anode_active": anode, "binder_and_carbon": inactive, "electrolyte": electrolyte,
         "electrolyte_salt": salt, "separator_m2": coated_m2 * d["separator_overlap"],
         "copper_foil": cu_foil, "aluminium_foil": al_foil}
    q = {k: v * per_yield for k, v in q.items()}
    elements = {e: cam * f * per_yield for e, f in frac.items() if e != "O"}
    exposure = {"lithium_carbonate": (li_cathode + li_electrolyte) / LI2CO3_LI_FRACTION * per_yield,
                "nickel": elements.get("Ni", 0.0), "cobalt": elements.get("Co", 0.0),
                "manganese": elements.get("Mn", 0.0), "copper": q["copper_foil"],
                "aluminium": q["aluminium_foil"] + elements.get("Al", 0.0)}
    return {"chemistry": chem, "anode": d["anode"], "lithium_cell": lithium_cell, "quantities": q,
            "cathode_elements": elements, "exposure": exposure,
            "lithium_in_cathode_kg": li_cathode * per_yield, "lithium_in_electrolyte_kg": li_electrolyte * per_yield,
            "cathode_mass_fractions": frac, "ah_per_kwh": ah}


def chemistries():
    return list(load("cell_design")["cells"])
