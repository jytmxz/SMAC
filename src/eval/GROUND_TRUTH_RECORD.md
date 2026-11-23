# GROUND_TRUTH_RECORD
# GROUND_TRUTH_RECORD

## 1. Data Sources

| File | Granularity | Coverage | Columns Used |
|---|---|---|---|
| `patronage-southeast-queensland.csv` | Month × Mode | 2023-12 – 2026-06 | `Month-Year`, `Mode`, `Passenger trips` |
| `citytrain-punctuality-and-rel.csv` | Monthly | 2023-12 – 2026-06 | `Citytrain: On-time running (combined peaks)` |
| `seq-bus-punctuality.csv` | Monthly | 2023-11 – 2026-06 | `SEQ Bus: On-time running (overall)` |
| `seq-tram-punctuality-and-reli_1.csv` | Monthly | 2023-12 – 2026-06 | `SEQ Tram: Punctuality` |
| `complaints.csv` | Weekly | 2012-07 – 2026-06-28 | `Week ending`, `Passenger trips`, two complaint count columns |
| `customer-experience-overall_1.csv` | Month × Category | 2026-01 – 2026-06 | `NETWORK-Ease of using the service overall` |

**Complaints Data Gap:**

- Nine weeks of complaint data are missing, from week ending 2026-02-01 to 2026-03-29.
- Consequently, monthly `complaint_rate` values are unavailable for February and March 2026.
- This explains why the full-window complaint correlation has n = 29 rather than 31.
- The analysis window in Use Case 11 is not affected.

**Unified Analysis Window:**

The unified analysis window starts in **2023-12**, which is the earliest common month covered by patronage and all three punctuality datasets.

Although Bus punctuality data starts in 2023-11, months outside the unified window are not included in the calculations.

---

## 2. Metric Definitions

The following definitions were derived from the original ground truth. All four correlation use cases match the expected results **exactly to four decimal places** under these definitions.

These definitions should be used consistently in the tool descriptions.

| Signal | Definition |
|---|---|
| `patronage` (for correlation analysis) | The monthly sum of **Bus + Citytrain + Tram** passenger trips, **excluding Ferry**. |
| `complaint_rate` | Group weekly records by the calendar month of their `Week ending` date, then calculate `(Σ go card complaints + Σ other complaints) / Σ Passenger trips × 10,000`. |
| `on_time_running` | The **simple arithmetic mean** of the punctuality rates of Citytrain, SEQ Bus, and SEQ Tram (not weighted by passenger volume). |
| `customer_experience` | The monthly score from the `NETWORK-Ease of using the service overall` row. |
| `change_pct` | `(end_value − start_value) / start_value`, expressed as a decimal and rounded to 4 decimal places. |

### 2.1 Correlation Statistics

For two aligned monthly sequences, x and y, within the analysis window (n months):

1. **r_raw**: The Pearson correlation coefficient between x and y.

2. **r_diff**: The Pearson correlation coefficient between their first-order differences:

   - Δx_t = x_t − x_(t−1)
   - Δy_t = y_t − y_(t−1)

   There are n−1 pairs of differences. Differencing helps remove spurious correlations caused by shared trends and seasonal levels.

3. **significant**: A two-sided t-test is applied to `r_raw`:

   `t = r·√(n−2) / √(1−r²)`

   - Degrees of freedom: `df = n−2`
   - If **p < 0.05**, `significant = true`.

---

## 3. Ground Truth Calculation by Use Case

### Use Case 1: Monthly Bus Patronage (2024-01 – 2024-03)

- **Category**: hand-calculated / authoritative value
- **Call**: `get_patronage(mode="bus", start_month="2024-01", end_month="2024-03")`

**Steps:**

1. Filter the patronage CSV for `Mode = Bus` and the months Jan-2024, Feb-2024, and Mar-2024.
2. Read the `Passenger trips` column.

| Month | Trips |
|---|---:|
| 2024-01 | 7,287,187 |
| 2024-02 | 9,504,336 |
| 2024-03 | 10,010,413 |

3. All three requested months are within the dataset coverage (2023-12 – 2026-06), so `complete_range = true`.

**Ground Truth:**

`complete_range: true`, together with the three values in the table above.

---

### Use Case 2: Invalid Date Format (get_patronage)

- **Call**: `start_month = "2024/01"`
- **Validation**: The date does not follow the required `YYYY-MM` format because it uses a slash instead of a hyphen.

**Ground Truth:**

`{"status":"out_of_scope","reason":"start_month"}`

---

### Use Case 3: Unsupported Mode – Ferry (get_patronage)

- **Call**: `mode = "ferry"`
- **Validation**: Ferry is not a supported patronage mode.

**Ground Truth:**

`{"status":"out_of_scope","reason":"ferry"}`

---

### Use Case 4: Date Range Before Dataset Start (get_patronage)

- **Call**: 1999-01 – 1999-06
- **Validation**: The earliest available month is 2023-12. The requested period falls entirely before the dataset coverage.

**Ground Truth:**

`{"status":"out_of_scope","reason":"2023-12"}`

---

### Use Case 5: Partial Coverage Must Not Be Treated as Complete Coverage

- **Call**: `get_patronage(start_month="2026-04", end_month="2026-08")`

**Steps:**

1. The requested months are 2026-04, 2026-05, 2026-06, 2026-07, and 2026-08, covering five months.
2. The updated dataset ends in **2026-06**, so July and August 2026 are missing.
3. Since some requested months are unavailable, `complete_range = false`.

**Ground Truth:**

`complete_range: false`

---

### Use Case 6: Citytrain Punctuality Change (2023-12 → 2024-07)

- **Call**: `get_mode_trend(mode="citytrain", metric="punctuality", 2023-12, 2024-07)`

**Steps:**

1. Read `On-time running (combined peaks)` from the Citytrain CSV:

   - Dec-2023 = **0.9314**
   - Jul-2024 = **0.927973**

2. Calculate the percentage change:

   `change_pct = (0.927973 − 0.9314) / 0.9314`

   `= −0.003427 / 0.9314`

   `= −0.003679`

3. Round to four decimal places:

   **−0.0037**

   This represents a relative change of −0.37%, not a percentage-point change.

**Ground Truth:**

`change_pct: -0.0037`

---

### Use Case 7: Invalid Month (2024-13)

- Month 13 is invalid.

**Ground Truth:**

`{"status":"out_of_scope","reason":"start_month"}`

---

### Use Case 8: Bus Reliability

- `seq-bus-punctuality.csv` contains punctuality data only and does **not** contain a reliability column.

**Ground Truth:**

`{"status":"out_of_scope","reason":"reliability"}`

---

### Use Case 9: Ferry Punctuality Trend

- No Ferry punctuality data is available in the datasets.

**Ground Truth:**

`{"status":"out_of_scope","reason":"ferry"}`

---

### Use Case 10: Citytrain Patronage Trend Before the Analysis Window

- The requested period is in 1999, which is earlier than the unified analysis window starting in 2023-12.

**Ground Truth:**

`{"status":"out_of_scope","reason":"2023-12"}`

---

### Use Case 11: Patronage vs Complaint Rate (2024-12 – 2025-03)

- **Call**: `analyze_service_relationship(signal_a="patronage", signal_b="complaint_rate", 2024-12, 2025-03)`

#### Step 1: Calculate Patronage (Bus + Citytrain + Tram)

| Month | Bus | Citytrain | Tram | **patronage** |
|---|---:|---:|---:|---:|
| 2024-12 | 7,976,981 | 3,608,590 | 1,232,692 | **12,818,263** |
| 2025-01 | 8,294,700 | 3,688,824 | 1,273,695 | **13,257,219** |
| 2025-02 | 10,466,067 | 4,649,021 | 1,152,885 | **16,267,973** |
| 2025-03 | 9,413,898 | 4,117,546 | 936,598 | **14,468,042** |

#### Step 2: Aggregate Weekly Complaint Data by Month and Calculate complaint_rate

Group weekly records according to the calendar month of their `Week ending` date.

| Month | Number of Weeks | Σ trips | Σ go card | Σ other | **complaint_rate** = (go + other) / trips × 10⁴ |
|---|---:|---:|---:|---:|---:|
| 2024-12 | 5 | 16,219,324 | 9 | 2,962 | **1.8318** |
| 2025-01 | 4 | 11,780,585 | 15 | 2,021 | **1.7283** |
| 2025-02 | 4 | 15,888,026 | 8 | 4,307 | **2.7159** |
| 2025-03 | 5 | 18,062,710 | 10 | 3,829 | **2.1254** |

**Calculation Example:**

For December 2024:

`complaint_rate = (9 + 2,962) / 16,219,324 × 10,000 = 1.8318`

#### Step 3: Correlation Analysis

- `r_raw` = Pearson(patronage, complaint_rate), n = 4 → **0.9747**
- `r_diff` = Pearson(Δpatronage, Δcomplaint_rate), 3 pairs of differences → **0.9843**
- `t = 0.9747·√2 / √(1−0.9747²) ≈ 6.16`
- Degrees of freedom: `df = 2`
- p = **0.025** < 0.05
- Therefore, `significant = true`.

**Ground Truth:**

- `r_raw: 0.9747`
- `r_diff: 0.9843`
- `n: 4`
- `significant: true`

---

### Use Case 12: Patronage vs On-Time Running (2023-12 – 2025-03)

- **Call**: `analyze_service_relationship(signal_a="patronage", signal_b="on_time_running", 2023-12, 2025-03)`

#### Step 1: Calculate Patronage

`patronage = Bus + Citytrain + Tram`

#### Step 2: Calculate on_time_running

`on_time_running = Simple arithmetic mean of the punctuality rates of the three transport modes`

| Month | patronage | Citytrain | Bus | Tram | **on_time_running** |
|---|---:|---:|---:|---:|---:|
| 2023-12 | 10,273,280 | 0.9314 | 0.9105 | 0.9510 | 0.930967 |
| 2024-01 | 11,151,300 | 0.9328 | 0.8856 | 0.9437 | 0.920700 |
| 2024-02 | 14,346,150 | 0.9173 | 0.8735 | 0.9458 | 0.912200 |
| 2024-03 | 15,023,859 | 0.8881 | 0.8637 | 0.9356 | 0.895800 |
| 2024-04 | 13,231,473 | 0.9228 | 0.8881 | 0.9420 | 0.917633 |
| 2024-05 | 14,999,107 | 0.9395 | 0.8922 | 0.9596 | 0.930433 |
| 2024-06 | 12,546,647 | 0.9103 | 0.9172 | 0.9696 | 0.932367 |
| 2024-07 | 14,572,091 | 0.927973 | 0.9008 | 0.9641 | 0.930958 |
| 2024-08 | 16,863,168 | 0.957893 | 0.8889 | 0.9576 | 0.934798 |
| 2024-09 | 15,258,716 | 0.962417 | 0.8957 | 0.9508 | 0.936306 |
| 2024-10 | 17,342,351 | 0.950307 | 0.8930 | 0.9654 | 0.936236 |
| 2024-11 | 15,842,570 | 0.931863 | 0.8733 | 0.9626 | 0.922588 |
| 2024-12 | 12,818,263 | 0.9071 | 0.8826 | 0.9589 | 0.916200 |
| 2025-01 | 13,257,219 | 0.957321 | 0.8903 | 0.9586 | 0.935407 |
| 2025-02 | 16,267,973 | 0.925723 | 0.8789 | 0.9613 | 0.921974 |
| 2025-03 | 14,468,042 | 0.938537 | 0.8674 | 0.9669 | 0.924279 |

**Calculation Example:**

For December 2023:

`on_time_running = (0.9314 + 0.9105 + 0.9510) / 3 = 0.930967`

#### Step 3: Correlation Analysis

- `r_raw`, n = 16 → **0.0952**
- `r_diff`, 15 pairs of differences → **−0.1733**
- `t = 0.0952·√14 / √(1−0.0952²) ≈ 0.358`
- Degrees of freedom: `df = 14`
- p = **0.73**
- Therefore, `significant = false`.

**Ground Truth:**

- `r_raw: 0.0952`
- `r_diff: -0.1733`
- `n: 16`
- `significant: false`

---

### Use Case 13: Identical Signals

- `signal_a == signal_b == "patronage"`

**Ground Truth:**

`{"status":"out_of_scope","reason":"different"}`

---

### Use Case 14: Invalid Signal Name

- `reliability` is not included in the list of supported signals.

**Ground Truth:**

`{"status":"out_of_scope","reason":"signal"}`

---

### Use Case 15: Patronage vs Customer Experience (2026-01 – 2026-06)

- **Call**: `analyze_service_relationship(signal_a="patronage", signal_b="customer_experience", 2026-01, 2026-06)`

#### Step 1: Determine Data Coverage

- `customer_experience` is only available for **2026-01 – 2026-06**, covering six months.
- The requested window exactly matches the available coverage, so no range adjustment is required.
- `range_adjusted = false`
- `effective_start = 2026-01`
- `effective_end = 2026-06`

#### Step 2: Data Sequences

| Month | patronage (B+C+T) | Ease of using the service overall |
|---|---:|---:|
| 2026-01 | 14,263,825 | 4.39 |
| 2026-02 | 17,034,682 | 4.39 |
| 2026-03 | 20,607,935 | 4.39 |
| 2026-04 | 17,013,678 | 4.31 |
| 2026-05 | 17,986,241 | 4.33 |
| 2026-06 | 17,316,794 | 4.36 |

#### Step 3: Correlation Analysis

- `r_raw`, n = 6 → **−0.0191**
- `r_diff`, 5 pairs of differences → **0.6137**
- p = **0.97**
- Therefore, `significant = false`.

**Ground Truth:**

- `range_adjusted: false`
- `effective_start: 2026-01`
- `effective_end: 2026-06`
- `n: 6`
- `r_raw: -0.0191`
- `r_diff: 0.6137`
- `significant: false`

---

### Use Case 16: Cross-Tool Consistency (Citytrain Patronage, 2023-12 → 2024-07)

- **Calls**:
  1. `get_patronage(mode="citytrain", 2023-12, 2024-07)`
  2. `get_mode_trend(mode="citytrain", metric="patronage", same time window)`

**Steps:**

1. Read Citytrain patronage from the patronage CSV:

   - Dec-2023 = **2,958,924**
   - Jul-2024 = **3,950,434**

2. Calculate the percentage change:

   `change_pct = (3,950,434 − 2,958,924) / 2,958,924`

   `= 991,510 / 2,958,924`

   `= 0.335091`

3. Round to four decimal places:

   **0.3351**

4. Both tools read from the same underlying sequence, so their start and end values must be identical.

**Ground Truth:**

- `start_value: 2958924`
- `end_value: 3950434`
- `change_pct: 0.3351`

---

## 4. Summary

| # | Category | Ground Truth | Current Status |
|---|---|---|---|
| 1 | Numerical value | Bus 7,287,187 / 9,504,336 / 10,010,413, `complete_range: true` | Unchanged |
| 2 | Invalid format | `out_of_scope: start_month` | Unchanged |
| 3 | Unsupported mode | `out_of_scope: ferry` | Unchanged (pending confirmation) |
| 4 | Before dataset start | `out_of_scope: 2023-12` | Unchanged |
| 5 | Partial coverage | `complete_range: false` | Value unchanged; note updated |
| 6 | Numerical value | `change_pct: -0.0037` | Unchanged |
| 7 | Invalid format | `out_of_scope: start_month` | Unchanged |
| 8 | Unsupported metric | `out_of_scope: reliability` | Unchanged |
| 9 | Unsupported mode | `out_of_scope: ferry` | Unchanged |
| 10 | Before analysis window | `out_of_scope: 2023-12` | Unchanged |
| 11 | Correlation | 0.9747 / 0.9843 / n=4 / significant | Unchanged; category/note updated |
| 12 | Correlation | 0.0952 / -0.1733 / n=16 / not significant | Unchanged; category/note updated |
| 13 | Identical signals | `out_of_scope: different` | Unchanged |
| 14 | Invalid signal | `out_of_scope: signal` | Unchanged |
| 15 | Correlation + coverage | -0.0191 / 0.6137 / n=6 / not significant / `range_adjusted: false` | Unchanged (pending confirmation); note updated |
| 16 | Cross-tool consistency | 2,958,924 → 3,950,434, `change_pct: 0.3351` | Unchanged; tool name updated |

---


## 7. 复现脚本

```python
import csv, datetime as dt
import numpy as np
from scipy import stats

def mkey(s):  # "Dec-2023" -> "2023-12"
    return dt.datetime.strptime(s, "%b-%Y").strftime("%Y-%m")

# patronage: Bus + Citytrain + Tram
pat = {}
for r in csv.DictReader(open("patronage-southeast-queensland.csv")):
    pat.setdefault(r["Mode"], {})[mkey(r["Month-Year"])] = int(r["Passenger trips"])
P = {m: pat["Bus"][m] + pat["Citytrain"][m] + pat["Tram"][m] for m in pat["Bus"]}

def series(path, col=1):
    out = {}
    for r in list(csv.reader(open(path)))[1:]:
        out[mkey(r[0])] = float(r[col])
    return out

ct   = series("citytrain-punctuality-and-rel.csv")
bus  = series("seq-bus-punctuality.csv")
tram = series("seq-tram-punctuality-and-reli_1.csv")
otr  = {k: (ct[k] + bus[k] + tram[k]) / 3 for k in set(ct) & set(bus) & set(tram)}

agg = {}
for r in list(csv.reader(open("complaints.csv")))[1:]:
    k = dt.datetime.strptime(r[0], "%a, %d %b %Y %I:%M %p").strftime("%Y-%m")
    a = agg.setdefault(k, [0.0, 0.0])
    a[0] += float(r[1])
    a[1] += float(r[2] or 0) + float(str(r[3]).replace(",", "") or 0)
cr = {k: c / t * 1e4 for k, (t, c) in agg.items()}

def analyze(a, b, start, end):
    ks = [k for k in sorted(set(a) & set(b)) if start <= k <= end]
    x = np.array([a[k] for k in ks]); y = np.array([b[k] for k in ks])
    r_raw, p = stats.pearsonr(x, y)
    r_diff = np.corrcoef(np.diff(x), np.diff(y))[0, 1]
    return dict(r_raw=round(r_raw, 4), r_diff=round(r_diff, 4),
                n=len(ks), significant=bool(p < 0.05))

print(analyze(P, cr,  "2024-12", "2025-03"))  # 用例 11
print(analyze(P, otr, "2023-12", "2025-03"))  # 用例 12
```
