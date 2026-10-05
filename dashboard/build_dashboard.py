"""Build the dashboard from the files written by `python -m batterycost.run`."""
import datetime, json, pathlib
import pandas as pd

HERE, OUT = pathlib.Path(__file__).parent, pathlib.Path("outputs")


def main():
    rec = lambda df: json.loads(df.to_json(orient="records"))
    h = pd.read_csv(OUT / "cost_history_china.csv")
    p = pd.read_csv(OUT / "prices_monthly.csv")
    wide = h.pivot(index="month", columns="chemistry", values="cell_cost")
    history = {"months": list(wide.index), **{c: wide[c].round(2).tolist() for c in wide.columns},
               "lithium_carbonate_usd_t": (p.lithium_carbonate_usd_kg * 1000).round(0).tolist()}
    data = {"built": datetime.date.today().isoformat(),
            "summary": json.loads((OUT / "summary.json").read_text()), "history": history,
            "coef": rec(pd.read_csv(OUT / "contract_coefficients.csv")),
            "automakers": rec(pd.read_csv(OUT / "automaker_exposure.csv")),
            "vehicle_rows": int(len(pd.read_csv(OUT / "vehicle_exposure.csv"))),
            "validation": rec(pd.read_csv(OUT / "validation.csv")),
            "sensitivity": rec(pd.read_csv(OUT / "design_sensitivity.csv"))}
    page = (HERE / "template.html").read_text().replace("/*DATA*/", json.dumps(data))
    (OUT / "dashboard_fragment.html").write_text(page)
    (OUT / "dashboard.html").write_text('<!doctype html><html lang="en"><head><meta charset="utf-8">'
                                        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
                                        '<body style="margin:0">' + page + "</body></html>")
    print(f"wrote {OUT/'dashboard.html'} ({len(page)//1024} KB)")


if __name__ == "__main__":
    main()
