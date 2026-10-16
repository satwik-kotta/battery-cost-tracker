"""Price risk: how far could cell cost move in the next 12 months?

Method: resample history. Twelve-month price paths are built by stitching together random blocks of
past monthly returns for all six metals at once, so months stay in sequence within a block and the
metals keep moving together the way they did. No distribution is assumed.
"""
import numpy as np, pandas as pd
from .bom import DRIVERS, chemistries
from .cost import cost_history, exposure_table
from .prices import fit_lithium_carbonate, parse_imf
from . import load

METALS = ["lithium_metal", "nickel", "cobalt", "manganese", "copper", "aluminium"]


def simulate(metals, horizon=12, paths=5000, block=6, seed=0, vol_adjust=True, decay=0.9):
    """Simulated metal prices `horizon` months ahead. Shape (paths, 6), USD per ton.

    With vol_adjust, each past return is first divided by the volatility prevailing at the time
    (an exponentially weighted average of recent squared returns) and the resampled returns are then
    scaled to today's volatility. Calm history is stretched when markets are turbulent, and vice versa.
    """
    rng = np.random.default_rng(seed)
    r = np.log(metals[METALS]).diff().dropna().to_numpy()
    if vol_adjust:
        var = np.empty_like(r)
        var[0] = r[:12].var(axis=0)
        for t in range(1, len(r)):
            var[t] = decay * var[t - 1] + (1 - decay) * r[t - 1] ** 2
        current = decay * var[-1] + (1 - decay) * r[-1] ** 2
        r = r / np.sqrt(var) * np.sqrt(current)
    n_blocks = int(np.ceil(horizon / block))
    starts = rng.integers(0, len(r) - block + 1, size=(paths, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(paths, -1)[:, :horizon]
    return metals[METALS].iloc[-1].to_numpy() * np.exp(r[idx].sum(axis=1))


def _driver_prices(sim, slope, intercept, floor):
    """Convert simulated metal prices (USD/t) into driver prices (USD/kg), mapping lithium metal to carbonate."""
    d = sim / 1000.0
    d[:, 0] = np.maximum(slope * sim[:, 0] + intercept, floor) / 1000.0
    return d                                         # column order matches DRIVERS


def cost_at_risk(metals, horizon=12, paths=5000, seed=0, fit=None, vol_adjust=True):
    """Distribution of the change in cell cost per kWh over the horizon, by chemistry."""
    _, diag = fit_lithium_carbonate(metals) if fit is None else (None, fit)
    floor = load("prices")["lithium_carbonate_floor_usd_t"]
    sim = _driver_prices(simulate(metals, horizon, paths, seed=seed, vol_adjust=vol_adjust), diag["slope"], diag["intercept"], floor)
    now = _driver_prices(metals[METALS].iloc[[-1]].to_numpy().copy(), diag["slope"], diag["intercept"], floor)[0]
    exp = exposure_table()[DRIVERS].to_numpy()                 # chemistries x drivers
    change = (sim - now) @ exp.T                              # paths x chemistries, USD per kWh
    q = np.quantile(change, [0.05, 0.25, 0.5, 0.75, 0.95], axis=0)
    out = pd.DataFrame(q.T, index=chemistries(), columns=["p05", "p25", "p50", "p75", "p95"])
    out["prob_increase"] = (change > 0).mean(axis=0)
    return out, change


def backtest(metals, first_origin="2018-01", horizon=12, paths=2000, vol_adjust=True):
    """Was the 90% range right 90% of the time?

    At each past month, simulate using only data up to that month, then check whether the cost that
    actually followed 12 months later fell inside the simulated 5th-95th percentile range.
    The lithium mapping is refit at each origin on the full anchor set (anchors are few), so this
    tests the price simulation, not the mapping.
    """
    _, diag = fit_lithium_carbonate(metals)
    floor = load("prices")["lithium_carbonate_floor_usd_t"]
    exp = exposure_table()[DRIVERS].to_numpy()
    rows = []
    months = metals.index
    for i in range(months.get_loc(pd.Period(first_origin, "M")), len(months) - horizon):
        hist = metals.iloc[: i + 1]
        sim = _driver_prices(simulate(hist, horizon, paths, seed=i, vol_adjust=vol_adjust), diag["slope"], diag["intercept"], floor)
        now = _driver_prices(hist[METALS].iloc[[-1]].to_numpy().copy(), diag["slope"], diag["intercept"], floor)[0]
        fut = _driver_prices(metals[METALS].iloc[[i + horizon]].to_numpy().copy(), diag["slope"], diag["intercept"], floor)[0]
        lo, hi = np.quantile((sim - now) @ exp.T, [0.05, 0.95], axis=0)
        actual = (fut - now) @ exp.T
        for c, l, h, a in zip(chemistries(), lo, hi, actual):
            rows.append({"origin": str(months[i]), "chemistry": c, "low": l, "high": h, "actual": a, "inside": bool(l <= a <= h)})
    bt = pd.DataFrame(rows)
    return bt, bt.groupby("chemistry").inside.mean()


def cost_scenarios(hist, now_cost, fit, horizon=12, paths=5000, seed=0, vol_adjust=True):
    """Simulated cell cost per kWh `horizon` months ahead, by chemistry, using only the history passed in.

    Same price simulation as `cost_at_risk`; returns absolute cost (USD/kWh, paths x chemistries) instead of
    the change, so an optimiser can work with it directly. `now_cost` is the current cell cost per kWh for each
    chemistry in `chemistries()` order; `fit` is the lithium carbonate mapping from `fit_lithium_carbonate`.
    """
    floor = load("prices")["lithium_carbonate_floor_usd_t"]
    sim = _driver_prices(simulate(hist, horizon, paths, seed=seed, vol_adjust=vol_adjust), fit["slope"], fit["intercept"], floor)
    now = _driver_prices(hist[METALS].iloc[[-1]].to_numpy().copy(), fit["slope"], fit["intercept"], floor)[0]
    exp = exposure_table()[DRIVERS].to_numpy()
    return np.asarray(now_cost)[None, :] + (sim - now) @ exp.T
