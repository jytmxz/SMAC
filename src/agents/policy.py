"""
agents/policy.py - your Policy & Patronage agent.

    python agents/policy.py     # serves on :8000

The server wiring is done, and get_patronage is written out as a worked
example. Read it, then build tools of your own.

Note on the data: the series is monthly totals with no geography, which is why
geocode_place is not registered below. Patronage moved after the 50c fare, but
so did the school term and the weather - report the change, not a cause.

Import note: use `from mcp.server import MCPServer`. Most tutorials show
`FastMCP`, which is not in the SDK version this course requires.
"""
from __future__ import annotations
import math
import re
import statistics
from datetime import datetime
from typing import Annotated, Optional
from pydantic import Field
import os
import sys
from pathlib import Path
from collections import defaultdict





sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server import MCPServer

import common
import data
import llm                                 # llm.ask() writes prose about your results
from smac import check_identity, guard, out_of_scope, respond

# Change {slot} to your approved capability slot.
AGENT_NAME = "smac-policy"
VERSION = "0.1.0"

check_identity(AGENT_NAME, VERSION)
mcp = MCPServer(name=AGENT_NAME, version=VERSION)

# health comes from common.py. No geocode_place here: this data has no
# geography, and an unused tool only attracts calls meant for another agent.
common.register(mcp, agent_name=AGENT_NAME, version=VERSION,
                data_sources=[data.PATRONAGE_LICENCE], geocode=False)

# common.register(
#     mcp, agent_name=AGENT_NAME, version=VERSION,
#     data_sources=[data.PATRONAGE_LICENCE, data.TRANSLINK_PERFORMANCE_LICENCE],
#     geocode=False,
# )



import data
from smac import guard, respond, out_of_scope

# ---------------------------------------------------------------------------
# Shared constants and helpers
# ---------------------------------------------------------------------------

_MODE_MAP = {"bus": "Bus", "citytrain": "Citytrain", "tram": "Tram"}
# Ferry deliberately absent: "ferry 排除在这套工具外" - a ferry request must
# be declined, not silently ignored or silently included.

_PUNCTUALITY_LOADERS = {
    "bus": data.bus_punctuality,
    "citytrain": data.citytrain_punctuality,
    "tram": data.tram_punctuality,
}

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_month(value: str, param_name: str) -> Optional[str]:
    if not isinstance(value, str) or not _MONTH_RE.match(value):
        return f"{param_name} must be in YYYY-MM format, e.g. '2024-07' (got {value!r})."
    return None


def _validate_mode(value: str, param_name: str = "mode") -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or value.lower() not in _MODE_MAP:
        return (
            f"{param_name} must be one of 'bus', 'citytrain', 'tram' "
            f"(got {value!r}; ferry is not covered by this tool)."
        )
    return None


def _month_range(start_month: str, end_month: str) -> list[str]:
    """['2024-01', '2024-02', ...] inclusive."""
    start_y, start_m = map(int, start_month.split("-"))
    end_y, end_m = map(int, end_month.split("-"))
    months = []
    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m, y = 1, y + 1
    return months


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y, mx, my in ((x, y, mean_x, mean_y) for x, y in zip(xs, ys)))
    std_x, std_y = statistics.pstdev(xs), statistics.pstdev(ys)
    if std_x == 0 or std_y == 0:
        return 0.0
    return cov / (n * std_x * std_y)


def _first_diff(series: list[float]) -> list[float]:
    return [series[i] - series[i - 1] for i in range(1, len(series))]


# Standard two-tailed alpha=0.05 t critical values, df 1-30 (textbook table).
# Beyond df=30 we interpolate across the table's usual tail breakpoints
# (40/60/120/inf) rather than assuming the large-sample z=1.96 approximation
# from the first data point past 30 - the interpolation stays closer to the
# true t-distribution for moderate df.
_T_TABLE_1_30 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
    27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}
_T_TABLE_TAIL = [(40, 2.021), (60, 2.000), (120, 1.980), (float("inf"), 1.960)]


def _t_critical(df: int) -> float:
    if df < 1:
        return float("inf")
    if df <= 30:
        return _T_TABLE_1_30[df]
    prev_df, prev_t = 30, _T_TABLE_1_30[30]
    for bp_df, bp_t in _T_TABLE_TAIL:
        if df <= bp_df:
            if bp_df == float("inf"):
                return bp_t
            frac = (df - prev_df) / (bp_df - prev_df)
            return prev_t + frac * (bp_t - prev_t)
        prev_df, prev_t = bp_df, bp_t
    return 1.960


def _critical_r(n: int) -> float:
    """Two-tailed alpha=0.05 critical |r| for n paired observations.
    Returns 1.0 (i.e. "nothing can be significant") when n < 3."""
    df = n - 2
    if df < 1:
        return 1.0
    t = _t_critical(df)
    return t / math.sqrt(t * t + df)


def register(mcp) -> None:

    # -------------------------------------------------------------------
    # Tool 1 - get_patronage
    # -------------------------------------------------------------------
    @mcp.tool()
    @guard
    def get_patronage(
        start_month: Annotated[str, Field(description="First month to report, as YYYY-MM, e.g. '2024-07'.")],
        end_month: Annotated[str, Field(description="Last month to report, as YYYY-MM, e.g. '2025-06'.")],
        mode: Annotated[
            Optional[str],
            Field(description="'bus', 'citytrain' or 'tram'. Omit to return all three. Ferry is not covered."),
        ] = None,
    ) -> dict:
        """Return raw monthly South East Queensland patronage figures.

        Covers Bus, Citytrain and Tram (Ferry is out of scope for this tool
        set). Reports observed passenger-trip totals only - no change rate,
        no trend, no claim about what caused any month-to-month movement.
        Coverage runs from January 2012 through whatever month Translink has
        most recently published; a request outside that window, with
        start_month after end_month, or naming an unsupported mode is
        declined. When only part of the requested range has published data,
        the response says so explicitly via `complete_range` rather than
        silently returning a partial table.
        """
        error = (
            _validate_month(start_month, "start_month")
            or _validate_month(end_month, "end_month")
            or _validate_mode(mode)
        )
        if error:
            return out_of_scope(error, sources=[data.PATRONAGE_LICENCE])
        if start_month > end_month:
            return out_of_scope(
                f"start_month ({start_month}) must not be after end_month ({end_month}).",
                sources=[data.PATRONAGE_LICENCE],
            )

        modes_wanted = [_MODE_MAP[mode.lower()]] if mode else list(_MODE_MAP.values())
        all_records = data.patronage_seq()
        relevant = [r for r in all_records if r["mode"] in modes_wanted]
        if not relevant:
            return out_of_scope(
                "No patronage data available for the requested mode(s).",
                sources=[data.PATRONAGE_LICENCE],
            )

        data_start = min(r["month"] for r in relevant)[:7]
        data_end = max(r["month"] for r in relevant)[:7]
        if end_month < data_start or start_month > data_end:
            return out_of_scope(
                f"No patronage data between {start_month} and {end_month}. "
                f"Dataset covers {data_start} through {data_end}.",
                sources=[data.PATRONAGE_LICENCE],
            )

        start_key, end_key = f"{start_month}-01", f"{end_month}-01"
        window = [r for r in relevant if start_key <= r["month"] <= end_key]
        if not window:
            return out_of_scope(
                f"No patronage records found between {start_month} and {end_month}.",
                sources=[data.PATRONAGE_LICENCE],
            )

        by_mode: dict[str, list[dict]] = {}
        for r in window:
            by_mode.setdefault(r["mode"], []).append({"month": r["month"][:7], "trips": r["trips"]})

        requested_months = _month_range(start_month, end_month)
        complete_range = all(
            {r["month"] for r in by_mode.get(mm, [])} == set(requested_months) for mm in modes_wanted
        )

        return respond(
            {
                "start_month": start_month,
                "end_month": end_month,
                "modes": by_mode,
                "complete_range": complete_range,
            },
            sources=[data.PATRONAGE_LICENCE],
        )

    # -------------------------------------------------------------------
    # Tool 2 - get_mode_metric_trend
    # -------------------------------------------------------------------
    @mcp.tool()
    @guard
    def get_mode_trend(
        mode: Annotated[str, Field(description="'bus', 'citytrain' or 'tram'. Ferry is not covered.")],
        metric: Annotated[str, Field(description="'patronage' or 'punctuality' (on-time running). Reliability is not published for any mode and is not a valid value here.")],
        start_month: Annotated[str, Field(description="First month, as YYYY-MM.")],
        end_month: Annotated[str, Field(description="Last month, as YYYY-MM.")],
    ) -> dict:
        """Report how one metric changed for one mode between two months.

        `metric='patronage'` uses observed passenger trips; `metric=
        'punctuality'` uses on-time running. Both are anchored to the same
        coverage window - December 2023 through whichever month is most
        recently published for punctuality - regardless of which metric is
        requested, so a caller can't get a wider window just by asking for
        patronage (which is separately published back to 2012; use
        get_patronage for that longer history). Reliability was dropped
        project-wide (Bus never published a figure for it) and is not a
        valid `metric` value.

        Returns the start and end values and the percentage change between
        them. Reports what changed, not why - this tool makes no claim about
        cause, including no claim about any fare or policy change.
        """
        error = (
            _validate_mode(mode)
            or _validate_month(start_month, "start_month")
            or _validate_month(end_month, "end_month")
        )
        if error:
            return out_of_scope(error, sources=[data.TRANSLINK_PERFORMANCE_LICENCE])
        if metric not in ("patronage", "punctuality"):
            return out_of_scope(
                f"metric must be 'patronage' or 'punctuality' (got {metric!r}). "
                "Reliability is not published for any mode and was dropped project-wide.",
                sources=[data.TRANSLINK_PERFORMANCE_LICENCE],
            )
        if start_month > end_month:
            return out_of_scope(
                f"start_month ({start_month}) must not be after end_month ({end_month}).",
                sources=[data.TRANSLINK_PERFORMANCE_LICENCE],
            )

        canonical_mode = _MODE_MAP[mode.lower()]

        # Unified window: the latest month common to BOTH patronage and
        # punctuality for this mode, so the bound doesn't shift depending on
        # which metric was asked for.
        patronage_records = {
            r["month"][:7]: r["trips"]
            for r in data.patronage_seq() if r["mode"] == canonical_mode
        }
        punct_records = {
            r["month"][:7]: r["on_time_running"]
            for r in _PUNCTUALITY_LOADERS[mode.lower()]()
        }
        if not patronage_records or not punct_records:
            return out_of_scope(
                f"No data available for {canonical_mode}.",
                sources=[data.TRANSLINK_PERFORMANCE_LICENCE],
            )

        window_start = "2023-12"
        window_end = min(max(patronage_records), max(punct_records))

        if end_month < window_start or start_month > window_end:
            return out_of_scope(
                f"No {metric} data for {canonical_mode} between {start_month} and {end_month}. "
                f"This tool's coverage is {window_start} through {window_end}.",
                sources=[data.TRANSLINK_PERFORMANCE_LICENCE],
            )

        series = patronage_records if metric == "patronage" else punct_records
        if start_month not in series or end_month not in series:
            missing_end = "start_month" if start_month not in series else "end_month"
            return out_of_scope(
                f"No {metric} record for the requested {missing_end} "
                f"({start_month if missing_end == 'start_month' else end_month}) for {canonical_mode}.",
                sources=[data.TRANSLINK_PERFORMANCE_LICENCE],
            )

        start_value = series[start_month]
        end_value = series[end_month]
        change_pct = (
            (end_value - start_value) / start_value if start_value else None
        )

        return respond(
            {
                "mode": canonical_mode,
                "metric": metric,
                "start_month": start_month,
                "end_month": end_month,
                "start_value": start_value,
                "end_value": end_value,
                "change_pct": round(change_pct, 4) if change_pct is not None else None,
            },
            sources=[data.TRANSLINK_PERFORMANCE_LICENCE],
        )

    # -------------------------------------------------------------------
    # Tool 3 - analyze_service_relationship
    # -------------------------------------------------------------------
    _SIGNALS = {"patronage", "on_time_running", "complaint_rate", "customer_experience"}

    def _network_patronage() -> dict[str, int]:
        """Bus + Citytrain + Tram summed by month. Ferry excluded, matching
        this tool set's mode coverage everywhere else."""
        totals: dict[str, int] = {}
        for r in data.patronage_seq():
            if r["mode"] not in ("Bus", "Citytrain", "Tram"):
                continue
            m = r["month"][:7]
            totals[m] = totals.get(m, 0) + r["trips"]
        return totals

    def _network_on_time_running() -> dict[str, float]:
        """Simple (unweighted) mean of Bus/Citytrain/Tram on-time running,
        for months where all three modes have a published figure. A month
        with only partial mode coverage is left out rather than averaged
        over fewer modes - an average over 2 of 3 modes is a different,
        undocumented quantity and would silently change what 'network
        on-time running' means from month to month."""
        by_mode: dict[str, dict[str, float]] = {}
        for key, loader in _PUNCTUALITY_LOADERS.items():
            by_mode[key] = {r["month"][:7]: r["on_time_running"] for r in loader()}
        common_months = set(by_mode["bus"]) & set(by_mode["citytrain"]) & set(by_mode["tram"])
        return {
            m: statistics.mean(by_mode[k][m] for k in ("bus", "citytrain", "tram"))
            for m in common_months
        }

    def _network_complaint_rate() -> dict[str, float]:
        """Weekly complaints aggregated to monthly (sum counts and trips
        within the calendar month of each week's end-date, then recompute
        the rate from the monthly sums - not an average of weekly rates)."""
        buckets: dict[str, dict] = {}
        for r in data.complaints():
            week_end = datetime.strptime(r["week"], "%Y-%m-%d")
            m = week_end.strftime("%Y-%m")
            b = buckets.setdefault(m, {"complaints": 0, "trips": 0.0})
            b["complaints"] += r["go_card_complaints"] + r["other_complaints"]
            b["trips"] += r["trips"]
        return {
            m: (b["complaints"] / b["trips"] * 10_000) if b["trips"] else 0.0
            for m, b in buckets.items()
        }

    def _network_customer_experience() -> dict[str, float]:
        result = data.customer_experience_overall()
        return {r["month"][:7]: r["value"] for r in result["records"]}

    _SIGNAL_LOADERS = {
        "patronage": _network_patronage,
        "on_time_running": _network_on_time_running,
        "complaint_rate": _network_complaint_rate,
        "customer_experience": _network_customer_experience,
    }

    @mcp.tool()
    @guard
    def analyze_service_relationship(
        signal_a: Annotated[str, Field(description="One of: patronage, on_time_running, complaint_rate, customer_experience.")],
        signal_b: Annotated[str, Field(description="A different one of: patronage, on_time_running, complaint_rate, customer_experience.")],
        start_month: Annotated[
            Optional[str],
            Field(description="First month, as YYYY-MM. Defaults to 2023-12."),
        ] = None,
        end_month: Annotated[
            Optional[str],
            Field(description="Last month, as YYYY-MM. Defaults to the latest month common to both signals."),
        ] = None,
    ) -> dict:
        """Explore whether two network-level service signals move together.

        All four signals are network-wide (Bus+Citytrain+Tram; Ferry is not
        covered anywhere in this tool set): patronage is the three modes'
        trips summed; on_time_running is their simple (unweighted) monthly
        average; complaint_rate is complaints per 10,000 trips, aggregated
        from Translink's weekly published figures; customer_experience is
        the network "ease of using the service overall" rating from
        Translink's customer experience survey.

        customer_experience is published from December 2025 only (a much
        shorter window than the other three signals) and only the most
        recent ~6 months are kept by the publisher at any time - if either
        signal is customer_experience, the requested start_month is pushed
        forward to whatever the dataset's actual earliest available month
        is, and the response says so via `range_adjusted` and
        `effective_start_month` rather than silently using a shorter window
        than what was asked for.

        Reports both the raw-level Pearson correlation and the
        first-differenced (month-over-month change) correlation - not just
        one - because the two can disagree, and picking only the more
        striking figure would misrepresent what the data shows. Never
        implies causation in either direction: no control group, and no
        adjustment for confounders (fare changes, seasonality, service
        disruptions) that could move both signals independently.
        """
        if signal_a not in _SIGNALS or signal_b not in _SIGNALS:
            bad = signal_a if signal_a not in _SIGNALS else signal_b
            return out_of_scope(
                f"signal must be one of {sorted(_SIGNALS)} (got {bad!r}).",
                sources=[data.TRANSLINK_PERFORMANCE_LICENCE],
            )
        if signal_a == signal_b:
            return out_of_scope(
                "signal_a and signal_b must be different.",
                sources=[data.TRANSLINK_PERFORMANCE_LICENCE],
            )

        requested_start = start_month or "2023-12"
        if _validate_month(requested_start, "start_month"):
            return out_of_scope(_validate_month(requested_start, "start_month"),
                                 sources=[data.TRANSLINK_PERFORMANCE_LICENCE])
        if end_month and _validate_month(end_month, "end_month"):
            return out_of_scope(_validate_month(end_month, "end_month"),
                                 sources=[data.TRANSLINK_PERFORMANCE_LICENCE])

        series_a = _SIGNAL_LOADERS[signal_a]()
        series_b = _SIGNAL_LOADERS[signal_b]()
        if not series_a or not series_b:
            empty = signal_a if not series_a else signal_b
            return out_of_scope(f"No data currently available for signal {empty!r}.",
                                 sources=[data.TRANSLINK_PERFORMANCE_LICENCE])

        # customer_experience clamp
        effective_start = requested_start
        range_adjusted = False
        if "customer_experience" in (signal_a, signal_b):
            ce_series = series_a if signal_a == "customer_experience" else series_b
            ce_earliest = min(ce_series)
            if ce_earliest > effective_start:
                effective_start = ce_earliest
                range_adjusted = True

        effective_end = end_month or min(max(series_a), max(series_b))
        if effective_end < effective_start:
            return out_of_scope(
                f"No overlapping data: effective start ({effective_start}) is after "
                f"the requested/available end ({effective_end}).",
                sources=[data.TRANSLINK_PERFORMANCE_LICENCE],
            )

        common_months = sorted(
            m for m in (set(series_a) & set(series_b))
            if effective_start <= m <= effective_end
        )
        n = len(common_months)
        if n < 3:
            return out_of_scope(
                f"Only {n} month(s) of overlapping data between {signal_a} and {signal_b} "
                f"in the {effective_start} to {effective_end} window - too few to compute "
                "a meaningful correlation.",
                sources=[data.TRANSLINK_PERFORMANCE_LICENCE],
            )

        xs = [series_a[m] for m in common_months]
        ys = [series_b[m] for m in common_months]
        r_raw = _pearson(xs, ys)
        r_diff = _pearson(_first_diff(xs), _first_diff(ys)) if n >= 4 else None
        critical = _critical_r(n)
        significant = abs(r_raw) > critical

        caveats = [
            "Correlation does not imply causation: no control group and no adjustment "
            "for confounders (fare changes, seasonality, service disruptions).",
            "on_time_running is a simple (unweighted) average across Bus/Citytrain/Tram, "
            "not weighted by each mode's share of patronage.",
        ]
        if range_adjusted:
            caveats.append(
                f"start_month was adjusted from {requested_start} to {effective_start} "
                "because customer_experience has no published data before that month."
            )

        return respond(
            {
                "signal_a": signal_a,
                "signal_b": signal_b,
                "r_raw": round(r_raw, 4),
                "r_diff": round(r_diff, 4) if r_diff is not None else None,
                "n": n,
                "significant": significant,
                "effective_start_month": effective_start,
                "effective_end_month": effective_end,
                "range_adjusted": range_adjusted,
                "caveats": caveats,
            },
            sources=[data.TRANSLINK_PERFORMANCE_LICENCE],
        )

    return get_patronage, get_mode_trend, analyze_service_relationship

register(mcp)

if __name__ == "__main__":
    # 127.0.0.1 on your UQCloud zone. Docker sets HOST=0.0.0.0 so the port reaches your laptop.
    mcp.run(transport="streamable-http", host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "8000")))
