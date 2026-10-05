"""Market prices: read the IMF feed, and turn metal prices into the prices of what a cell plant buys."""
import re, urllib.request
import numpy as np, pandas as pd
from . import ROOT, load

IMF_URL = ("https://api.imf.org/external/sdmx/2.1/data/IMF.RES,PCPS,9.0.0/"
           ".PLITH+PCOBA+PNICK+PMANGELE+PCOPP+PALUM..M?startPeriod=2012-01")
SNAPSHOT = ROOT / "data" / "raw" / "imf_pcps.xml"
LI2CO3_LI_FRACTION = 2 * 6.941 / 73.891          # mass share of lithium in lithium carbonate


def fetch_imf(path=SNAPSHOT):
    """Download the latest IMF Primary Commodity Prices for the six battery metals."""
    req = urllib.request.Request(IMF_URL, headers={"User-Agent": "battery-cost-tracker"})
    path.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    return path


def parse_imf(path=SNAPSHOT):
    """Monthly USD-per-ton prices, one column per metal."""
    raw, names = path.read_text(), load("prices")["imf_series"]
    out = {}
    for attrs, body in re.findall(r"<Series ([^>]*)>(.*?)</Series>", raw, flags=re.S):
        a = dict(re.findall(r'(\w+)="([^"]*)"', attrs))
        if a.get("DATA_TRANSFORMATION") != "USD" or a.get("INDICATOR") not in names:
            continue
        obs = re.findall(r'TIME_PERIOD="(\d{4})-M(\d{2})" OBS_VALUE="([^"]+)"', body)
        out[names[a["INDICATOR"]]] = pd.Series({pd.Period(f"{y}-{m}", "M"): float(v) for y, m, v in obs})
    df = pd.DataFrame(out).sort_index().dropna()
    if df.empty or set(df.columns) != set(names.values()):
        raise ValueError("IMF file is missing one or more of the six metal series")
    df.index.name = "month"
    return df


def fit_lithium_carbonate(metals):
    """Straight-line map from the IMF lithium-metal series to battery-grade lithium carbonate.

    Annual anchors are matched to the annual mean of the metal series, monthly anchors to that month.
    Returns the fitted series plus fit diagnostics, including leave-one-out errors.
    """
    cfg = load("prices")
    x, y, labels = [], [], []
    for a in cfg["lithium_carbonate_anchors"]:
        p = str(a["period"])
        m = metals.lithium_metal[metals.index.year == int(p)].mean() if len(p) == 4 else metals.lithium_metal[pd.Period(p, "M")]
        x.append(m); y.append(a["usd_t"]); labels.append(p)
    x, y = np.array(x), np.array(y, float)
    slope, intercept = np.polyfit(x, y, 1)
    pred = slope * x + intercept
    loo = []
    for i in range(len(x)):                          # refit without each anchor, predict it
        k = np.arange(len(x)) != i
        s, c = np.polyfit(x[k], y[k], 1)
        loo.append(s * x[i] + c)
    diag = {"slope": float(slope), "intercept": float(intercept),
            "r2": float(1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()),
            "mean_abs_pct_error_leave_one_out": float(np.mean(np.abs(np.array(loo) - y) / y)),
            "anchors": [{"period": l, "published": float(b), "fitted": float(f), "leave_one_out": float(o)}
                        for l, b, f, o in zip(labels, y, pred, loo)]}
    series = (slope * metals.lithium_metal + intercept).clip(lower=cfg["lithium_carbonate_floor_usd_t"])
    return series, diag


def drivers(metals=None):
    """The six prices the cost model is driven by, in USD per kg, and the lithium fit diagnostics."""
    metals = parse_imf() if metals is None else metals
    carbonate, diag = fit_lithium_carbonate(metals)
    d = pd.DataFrame({"lithium_carbonate": carbonate / 1000, "nickel": metals.nickel / 1000,
                      "cobalt": metals.cobalt / 1000, "manganese": metals.manganese / 1000,
                      "copper": metals.copper / 1000, "aluminium": metals.aluminium / 1000})
    return d, diag
