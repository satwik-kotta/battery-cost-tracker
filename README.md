# Battery Cell Cost Tracker

What an EV battery cell should cost to make, recomputed every month from market prices.
The bill of materials is derived from each chemistry's formula and cell design; six IMF metal prices drive it.

```
IMF Primary Commodity Prices (monthly: lithium, nickel, cobalt, manganese, copper, aluminium)
        |                                 assumptions/*.yaml  (every number has a source or is marked as an assumption)
        v                                          |
 prices.py   lithium metal -> lithium carbonate    v
        |    (fit to USGS anchors)          bom.py   formula -> mass fractions -> kg per kWh
        +------------------+------------------+
                           v
                       cost.py   monthly cell and pack cost, exact attribution, contract coefficients, break-evens
                      /       \
               risk.py         vehicles.py
   12-month cost-at-risk,      exposure per EV model and by automaker
   backtested                  (Kelley Blue Book 2025 US sales)
```

## Results (prices through 2026-08)

| Chemistry | Cell cost, China, USD/kWh | 12-month change | Of which market-priced metals | kg lithium carbonate per kWh | kg nickel per kWh | kg cobalt per kWh | 12-month range, 5th to 95th percentile |
|---|---|---|---|---|---|---|---|
| NMC 811 | $68.3 | +11.4 | $32.8 | 0.590 | 0.709 | 0.089 | -10.5 to +54.7 |
| NMC 622 | $72.5 | +13.8 | $36.5 | 0.618 | 0.558 | 0.187 | -12.1 to +59.4 |
| NCA | $67.3 | +10.6 | $31.7 | 0.591 | 0.799 | 0.045 | -10.0 to +53.8 |
| LFP | $58.3 | +8.1 | $16.6 | 0.538 | 0.000 | 0.000 | -8.2 to +44.8 |
| Sodium-ion (NFPP) | $55.7 | +0.3 | $1.5 | 0.000 | 0.000 | 0.000 | -0.4 to +0.8 |

- **What moved cost:** from 2025-08 to 2026-08 an NMC 811 cell rose $11.4/kWh, of which lithium $6.6, cobalt $2.0, copper $1.3, nickel $1.3. LFP rose $8.1, of which lithium $6.0. The split is exact because cost is linear in the six prices.
- **Sodium-ion break-even:** a sodium-ion cell costs the same per kWh as LFP when lithium carbonate is at $13,961/t. The current estimate is $18,825/t. Lithium has been above the break-even in 20% of months since 2012. Sodium-ion's lower energy density is not priced here.
- **Risk:** the 12-month range comes from resampling 171 months of joint price history scaled to current volatility. Backtested over 92 past months, the stated 90% range held 71% of the time (49% without volatility scaling). It is a floor on the risk, not a bound.
- **Contract coefficients:** the kg-per-kWh columns are also price-adjustment coefficients. A $1/kg move in nickel moves an NMC 811 cell by $0.71/kWh. See `outputs/contract_coefficients.csv`.

### Exposure by automaker (2025 US sales, 97% of the market)

| Automaker | Sales | Avg pack kWh | Battery-metal cost per vehicle | 12-month change | Total per year at 2025 volume |
|---|---|---|---|---|---|
| General Motors | 169,764 | 117 | $3,833 | +$1,338 | $227M |
| Lucid | 12,614 | 112 | $3,550 | +$1,182 | $15M |
| Stellantis | 18,341 | 100 | $3,276 | +$1,144 | $21M |
| Volkswagen Group | 44,321 | 98 | $3,204 | +$1,121 | $50M |
| Rivian | 42,098 | 109 | $2,925 | +$1,113 | $47M |
| Mercedes-Benz | 12,942 | 96 | $3,145 | +$1,098 | $14M |
| Honda | 51,199 | 89 | $2,915 | +$1,018 | $52M |
| BMW Group | 44,941 | 89 | $2,913 | +$1,017 | $46M |
| Toyota | 22,009 | 72 | $2,627 | +$993 | $22M |
| Subaru | 10,715 | 72 | $2,627 | +$993 | $11M |
| Volvo | 10,512 | 86 | $2,821 | +$985 | $10M |
| Ford | 84,113 | 92 | $2,616 | +$969 | $81M |
| Hyundai Motor Group | 103,437 | 79 | $2,583 | +$901 | $93M |
| Nissan | 20,055 | 72 | $2,417 | +$857 | $17M |
| Tesla | 589,160 | 80 | $2,548 | +$851 | $501M |

These are replacement costs at market prices. Automakers buy under contracts with lags and hedges, so what they pay moves later and less.

## Validation

None of these figures were used to fit the model.

| Check | Model | Published | Gap | Source |
|---|---|---|---|---|
| LFP cathode price, 2023 (USD/kg) | 12.2 | 13 | -6% | Argonne ANL/CSE-24/1 Table 11 |
| NMC622 cathode price, 2023 (USD/kg) | 33.0 | 31.9 | +4% | Argonne ANL/CSE-24/1 Table 11 |
| NMC811 cell cost, China, 2024-05 to 2025-04 (USD/kWh) | 59.2 | 69 to 75 | -18% | CellEst 3.0 total cell cost |
| LFP cell cost, China, 2024-05 to 2025-04 (USD/kWh) | 51.9 | 56 to 62 | -12% | CellEst 3.0 total cell cost |
| NFPP cell cost, China, 2024-09 to 2025-04 (USD/kWh) | 55.4 | 57 to 66 | -10% | CellEst 3.0 total cell cost |
| LFP pack, 2025: model cost vs market price (USD/kWh) | 70.7 | 81 | -13% | BloombergNEF 2025 battery price survey, global average |
| NMC811 pack, 2025: model cost vs market price (USD/kWh) | 85.7 | 128 | -33% | BloombergNEF 2025 battery price survey, NMC global average |

- Cathode prices land within 6% of published values.
- Cell cost is 10% to 18% below the published range. The gap is in non-metal items (several are author assumptions), so the level is conservative while the month-to-month movement, which comes from metals, is unaffected.
- Pack rows compare model cost with market price, which includes supplier margin; the NMC survey average also includes low-volume Western packs.
- Lithium carbonate is inferred from the IMF lithium-metal series by a straight-line fit to 9 USGS-published prices: R² 0.997, leave-one-out error 7.8%.

## What is assumed, not sourced

Every input lives in `assumptions/` with a `source` line. The ones marked "Author assumption" are:
electrode loading, electrolyte loading, lithium excess, anode/cathode ratio, foil rolling fees, electrolyte
conversion and solvent cost, housing cost, Chinese separator price, all US manufacturing costs, pack integration cost,
the high-nickel NCA composition, and pack size and chemistry share for each vehicle (`assumptions/vehicles.csv`,
with a confidence column). `outputs/design_sensitivity.csv` shows how much each design input moves the result.

## Run it

```bash
pip install -r requirements.txt
python -m batterycost.run --refresh     # --refresh pulls the latest IMF prices; omit to use the saved snapshot
python dashboard/build_dashboard.py     # writes outputs/dashboard.html
python -m pytest -q tests               # 15 tests
```

## Tested and not tested

- Tested: full run from the saved IMF snapshot; 15 unit tests (stoichiometry against hand calculations, lithium mass balance, linearity, attribution adding up, break-even, reproducible simulation).
- Not tested: `--refresh` from this build environment, which cannot reach api.imf.org directly. The snapshot was downloaded from the same URL the script uses and the parser is tested on it.

## Sources

- IMF Primary Commodity Price System (monthly prices)
- USGS Mineral Commodity Summaries 2025 and 2026, Lithium (carbonate price anchors)
- Wesselkamper et al., CellEst 3.0, 2025 (capacities, voltages, cathode prices, production cost, cell-cost benchmarks)
- Argonne National Laboratory, ANL/CSE-24/1, 2024 (cathode prices, yields, component prices)
- Orangi et al., Communications Engineering, 2024 (capacities)
- BloombergNEF 2025 battery price survey (pack price benchmarks)
- Kelley Blue Book Q4 2025 Electric Vehicle Sales Report (US sales by model)
