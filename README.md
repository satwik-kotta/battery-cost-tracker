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
                  |
            optimize.py   cheapest chemistry mix for an energy density requirement (CVaR linear program), backtested
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

## Chemistry mix optimiser

Question: a buyer must meet a fleet energy density requirement. What mix of the five chemistries gives the lowest cost over the next 12 months, counting price risk?

Method: the price simulation gives 5,000 joint 12-month price scenarios, so 5,000 cost outcomes per chemistry. A linear program (SciPy, HiGHS) chooses shares that minimise `(1 - lambda) x expected cost + lambda x CVaR95`, where CVaR95 is the average cost in the worst 5% of scenarios (Rockafellar and Uryasev, 2000). Shares add to 1, sodium-ion is capped at 30% of volume, and the mix must meet a minimum stack energy density. `batterycost/optimize.py`, inputs in `assumptions/optimizer.yaml`.

**Result at 280 Wh/kg, prices through 2026-08** (cell cost, China, USD/kWh, 12 months ahead):

| Mix | Expected | CVaR95 (worst 5%) |
|---|---|---|
| **79% NCA, 21% sodium-ion (optimal)** | **73.3** | **129.9** |
| 100% NCA | 78.0 | 149.6 |
| 100% NMC 811 | 79.3 | 151.2 |

The optimal mix costs 6% less than buying only NCA in expectation and 13% less in the worst 5% of outcomes.

**What the requirement costs** (`outputs/optimizer_density_sweep.csv`, `outputs/optimizer_density.png`):

| Minimum stack Wh/kg | Mix | Expected | CVaR95 |
|---|---|---|---|
| 240 | 36% NCA, 34% LFP, 30% sodium-ion | 67.5 | 114.0 |
| 260 | 63% NCA, 7% LFP, 30% sodium-ion | 70.5 | 120.0 |
| 280 | 79% NCA, 21% sodium-ion | 73.3 | 129.9 |
| 300 | 90% NCA, 10% sodium-ion | 75.8 | 140.3 |
| 320 | about 100% NCA | 77.9 | 149.5 |

- **Cost and risk point the same way.** Sodium-ion and LFP are both the cheapest chemistries and the least exposed to metal prices, so moving the weight on risk from 0 to 1 changes no share at any requirement from 200 to 320 Wh/kg. The real trade-off is energy density, not risk.
- **Risk rises faster than cost.** From 240 to 300 Wh/kg expected cost rises 12% and CVaR95 rises 23%. Between 280 and 320 Wh/kg each extra 10 Wh/kg adds about $1.0 to $1.3/kWh of expected cost and $4.4 to $5.4/kWh of CVaR95.
- **The sodium-ion cap matters through the tail.** With no sodium-ion allowed, the 280 Wh/kg mix has almost the same expected cost (+0.6%) but a 9% higher CVaR95. See `outputs/optimizer_sensitivity.csv` for every assumption changed in turn.

**Backtest** (`outputs/optimizer_backtest_summary.csv`): at each of 92 past months (2018-01 to 2025-08), optimise with only the data up to then, hold the mix for 12 months, and price it at the cell cost that actually followed. 280 Wh/kg requirement, same constraints for the first three rows.

| Strategy | Mean realised cost | 95th percentile | Worst |
|---|---|---|---|
| Risk aware optimiser (lambda 0.5) | 64.1 | 92.3 | 104.0 |
| Expected cost optimiser (lambda 0) | 64.0 | 92.3 | 104.0 |
| Cheapest chemistry mix at today's prices, no simulation | 63.8 | 94.1 | 104.0 |
| 100% NCA | 67.5 | 102.2 | 114.1 |
| 100% NMC 811 | 67.8 | 101.8 | 115.0 |

Mixing in sodium-ion and LFP beat single nickel chemistry sourcing by about 5% on average and 10% at the 95th percentile. The simulation based optimiser did **not** beat the simple cheapest-today rule: its mean was $0.30/kWh higher and its 95th percentile $1.8/kWh lower, a difference too small to tell from noise. Monthly origins overlap, so there are only about 8 independent 12-month windows. The value here comes from the constraint aware blend, not from the price simulation.

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
python -m batterycost.optimize          # chemistry mix optimiser: writes outputs/optimizer_*; --skip-backtest for speed
python -m pytest -q tests               # 24 tests
```

## Tested and not tested

- Tested: full run from the saved IMF snapshot; 24 unit tests. The original 15 cover stoichiometry against hand calculations, lithium mass balance, linearity, attribution adding up, break-even and reproducible simulation. The 9 optimiser tests cover CVaR against a hand calculation, a toy problem with a known 50/50 answer, the LP's CVaR matching the CVaR of the mix it returns, no random feasible mix beating it, constraints holding, cost never falling as the requirement tightens, infeasible requirements raising an error, and scenarios ignoring all prices after the origin.
- Optimiser limits: every input in `assumptions/optimizer.yaml` is an author assumption (30% sodium-ion cap, 280 Wh/kg requirement, risk weight). Energy density is a stack proxy that leaves out separator, housing and tabs. Only metal prices move in the scenarios; fixed costs, volume discounts and contract terms are not modelled. Like the risk backtest, it fits the lithium price mapping once on the full anchor set.
- Not tested: `--refresh` from this build environment, which cannot reach api.imf.org directly. The snapshot was downloaded from the same URL the script uses and the parser is tested on it.

## Sources

- IMF Primary Commodity Price System (monthly prices)
- USGS Mineral Commodity Summaries 2025 and 2026, Lithium (carbonate price anchors)
- Wesselkamper et al., CellEst 3.0, 2025 (capacities, voltages, cathode prices, production cost, cell-cost benchmarks)
- Argonne National Laboratory, ANL/CSE-24/1, 2024 (cathode prices, yields, component prices)
- Orangi et al., Communications Engineering, 2024 (capacities)
- BloombergNEF 2025 battery price survey (pack price benchmarks)
- Kelley Blue Book Q4 2025 Electric Vehicle Sales Report (US sales by model)
