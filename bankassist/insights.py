"""Findings a manager can act on, derived from the two analytics reports.

This is the deterministic floor of the AI-insights feature, and the order of
the two layers is the design:

1. **Rules first.** Every finding here is a plain threshold over numbers the
   Overview and Performance endpoints already computed — explainable to a
   supervisor, testable, translated through the admin string table like any
   other label, and available with no model configured at all. The product's
   extractive-mode doctrine applies to its analytics too: the panel must
   never be empty because a credential is missing.
2. **The model writes prose on top, never facts underneath.** The optional
   Gemini narrative (`llm.summarize_operations`) receives a digest of these
   same aggregates and is instructed to use only the numbers it was given.
   If it is unavailable, the findings ARE the feature, not a degraded
   version of it.

**No customer text enters this module or the digest built from its output.**
The inputs are the aggregate payloads, and the one field of those that
carries customer wording (`top_topics`, already redacted upstream) is
deliberately never read here — a findings engine has no business quoting
anybody. That is what lets the whole feature sit behind `analytics.read`.

Each finding is `{key, severity, vars}`:

- `key` names an admin-strings template (`insight_<key>`), so the client
  renders it in the panel's own language with `{n}`-style interpolation —
  never sentence concatenation.
- `severity` is one of `SEVERITIES`: `act` (needs a decision today),
  `watch` (heading somewhere), `info` (worth knowing), `good` (working).
- `vars` are numbers and labels only.
"""

from __future__ import annotations

from typing import Any, Final

SEVERITIES: Final[tuple[str, ...]] = ("act", "watch", "info", "good")

# Thresholds, named so a future tuning session edits a constant rather than
# archaeology. Every rule also carries a floor on its denominator: a rate
# computed over three events is noise, and a finding built on noise teaches a
# manager to ignore the panel.
MIN_QUESTIONS: Final = 10          # before any rate-based finding fires
DEFLECTION_GOOD: Final = 0.70
DEFLECTION_SHIFT: Final = 0.05     # previous-window delta worth naming
OWN_CONTENT_LOW: Final = 0.50
SLOW_RESOLUTION_HOURS: Final = 48
MIN_RESOLVED: Final = 3
SLOW_DESK_FACTOR: Final = 1.5
MIN_LIVE_REQUESTS: Final = 4
ABANDON_RATE: Final = 0.25
MIN_LANG_QUESTIONS: Final = 5
LANG_MISS_RATE: Final = 0.40
PEAK_MIN_COUNT: Final = 4
PEAK_FACTOR: Final = 2.0


def _finding(key: str, severity: str, **vars_: Any) -> dict[str, Any]:
    assert severity in SEVERITIES
    return {"key": key, "severity": severity, "vars": vars_}


def _hours(seconds: int | None) -> int | None:
    return None if seconds is None else round(seconds / 3600)


def findings(overview: dict[str, Any], ops: dict[str, Any]) -> list[dict[str, Any]]:
    """Everything worth a manager's attention, most urgent first.

    Never returns an empty list: a window with nothing to flag gets the
    `all_quiet` finding, because an empty panel reads as broken rather than
    as good news.
    """
    out: list[dict[str, Any]] = []
    substantive = int(overview.get("substantive_questions") or 0)
    esc = ops.get("escalations") or {}
    live = ops.get("live") or {}
    staffing = ops.get("staffing") or {}

    # ---- needs a decision today
    urgent = int(esc.get("urgent_open") or 0)
    if urgent:
        out.append(_finding("urgent_open", "act", n=urgent))

    requested = int(live.get("requested") or 0)
    abandoned = int(live.get("abandoned") or 0)
    if requested >= MIN_LIVE_REQUESTS and abandoned / requested > ABANDON_RATE:
        out.append(_finding("abandonment", "act", n=abandoned, m=requested))

    own_rate = overview.get("own_content_rate")
    if substantive >= MIN_QUESTIONS and own_rate is not None and own_rate < OWN_CONTENT_LOW:
        out.append(_finding("own_content_low", "act", pct=round(own_rate * 100)))

    # ---- heading somewhere
    avg_res = esc.get("avg_resolution_seconds")
    resolved = int(esc.get("resolved") or 0)
    if (
        avg_res is not None
        and resolved >= MIN_RESOLVED
        and avg_res > SLOW_RESOLUTION_HOURS * 3600
    ):
        out.append(_finding("slow_resolution", "watch", h=_hours(avg_res)))

    if avg_res is not None and avg_res > 0:
        for desk in esc.get("desks") or []:
            desk_avg = desk.get("avg_resolution_seconds")
            if (
                desk_avg is not None
                and int(desk.get("resolved") or 0) >= MIN_RESOLVED
                and desk_avg > avg_res * SLOW_DESK_FACTOR
            ):
                out.append(
                    _finding(
                        "slow_desk", "watch",
                        desk=str(desk.get("label") or desk.get("department")),
                        h=_hours(desk_avg),
                    )
                )
                break  # the worst one is the finding; a list is a table's job

    if requested > 0 and int(staffing.get("on_duty_now") or 0) == 0:
        out.append(_finding("nobody_on", "watch"))

    deflection = overview.get("deflection_rate")
    previous = overview.get("previous") or {}
    prev_deflection = previous.get("deflection_rate")
    if (
        substantive >= MIN_QUESTIONS
        and deflection is not None
        and prev_deflection is not None
    ):
        if deflection - prev_deflection >= DEFLECTION_SHIFT:
            out.append(
                _finding(
                    "deflection_up", "good",
                    now=round(deflection * 100), then=round(prev_deflection * 100),
                )
            )
        elif prev_deflection - deflection >= DEFLECTION_SHIFT:
            out.append(
                _finding(
                    "deflection_down", "watch",
                    now=round(deflection * 100), then=round(prev_deflection * 100),
                )
            )

    for lang in overview.get("languages") or []:
        outcomes = lang.get("outcomes") or {}
        asked = sum(int(v) for v in outcomes.values())
        missed = int(outcomes.get("unanswered") or 0)
        if asked >= MIN_LANG_QUESTIONS and missed / asked > LANG_MISS_RATE:
            out.append(
                _finding(
                    "lang_gap", "watch",
                    language=str(lang.get("name") or lang.get("language")),
                    pct=round(missed / asked * 100),
                )
            )
            break  # one language finding; the Languages panel has the rest

    # ---- worth knowing
    hour_totals: dict[int, int] = {}
    for row in ops.get("busy") or []:
        _dow, hour, count = row
        hour_totals[int(hour)] = hour_totals.get(int(hour), 0) + int(count)
    if hour_totals:
        peak_hour, peak = max(hour_totals.items(), key=lambda kv: kv[1])
        mean = sum(hour_totals.values()) / len(hour_totals)
        if peak >= PEAK_MIN_COUNT and peak > mean * PEAK_FACTOR:
            # UTC on the wire, like the chart it summarises — the client
            # shifts to the operator's clock before rendering.
            out.append(_finding("peak_hour", "info", utc_hour=peak_hour))

    # ---- working
    if substantive >= MIN_QUESTIONS and deflection is not None and deflection >= DEFLECTION_GOOD:
        out.append(_finding("deflection_good", "good", pct=round(deflection * 100)))

    if not out:
        out.append(_finding("all_quiet", "info"))

    order = {s: i for i, s in enumerate(SEVERITIES)}
    out.sort(key=lambda f: order[str(f["severity"])])
    return out
