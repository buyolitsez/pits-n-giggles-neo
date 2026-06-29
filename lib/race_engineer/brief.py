# MIT License
#
# Copyright (c) [2026] [Ashwin Natarajan]
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# -------------------------------------- IMPORTS -----------------------------------------------------------------------

from typing import Any, Dict, List, Optional

from .agent_prompts import (
    ADVICE_CATEGORIES,
    CATEGORY_ALL,
    get_agent_prompt_specs,
    get_agent_prompt_texts,
    normalise_agent_focus,
)
from .review import review_race_engineer_advice

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

_CATEGORY_ALL = CATEGORY_ALL
_VALID_CATEGORIES = {_CATEGORY_ALL, *ADVICE_CATEGORIES}

_PRIORITY_RANK = {
    "critical": 0,
    "warning": 1,
    "advisory": 2,
    "info": 3,
}
_DRS_BATTLE_GAP_MS = 1000.0
_BATTLE_PACE_DELTA_MS = 250.0
_TYRE_STINT_LIMIT_WEAR_PCT = 70.0
_TYRE_PUNCTURE_RISK_WEAR_PCT = 80.0
_TYRE_STINT_WINDOW_LAPS = 5.0
_TYRE_PUNCTURE_WINDOW_LAPS = 3.0

RACE_ENGINEER_BRIEF_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "available": {"type": "boolean"},
        "connected": {"type": "boolean"},
        "last-update-timestamp": {"type": ["number", "null"]},
        "ok": {"type": "boolean"},
        "error": {"type": ["string", "null"]},
        "status": {"type": "string", "enum": ["ok", "error"]},
        "identity": {
            "type": "object",
            "properties": {
                "session_uid": {"type": ["integer", "null"]},
                "session_type": {"type": ["string", "null"]},
                "formula_type": {"type": ["string", "null"]},
                "circuit_name": {"type": ["string", "null"]},
                "session_ended": {"type": ["boolean", "null"]},
            },
            "additionalProperties": False,
        },
        "progress": {
            "type": "object",
            "properties": {
                "current_lap": {"type": ["integer", "null"]},
                "total_laps": {"type": ["integer", "null"]},
                "time_remaining_sec": {"type": ["number", "null"]},
            },
            "additionalProperties": False,
        },
        "reference_driver": {
            "type": "object",
            "properties": {
                "driver_index": {"type": ["integer", "null"]},
                "name": {"type": ["string", "null"]},
                "team": {"type": ["string", "null"]},
                "position": {"type": ["integer", "null"]},
                "is_player": {"type": ["boolean", "null"]},
            },
            "additionalProperties": False,
        },
        "nearby": {
            "type": "object",
            "properties": {
                "car_ahead": {"type": ["object", "null"]},
                "car_behind": {"type": ["object", "null"]},
            },
            "additionalProperties": False,
        },
        "brief_text": {"type": "string"},
        "advice": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "category": {"type": "string"},
                    "priority": {
                        "type": "string",
                        "enum": ["critical", "warning", "advisory", "info"],
                    },
                    "title": {"type": "string"},
                    "message": {"type": "string"},
                    "voice_callout": {"type": "string"},
                    "cooldown_key": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "metrics": {"type": "object"},
                },
                "required": [
                    "id",
                    "category",
                    "priority",
                    "title",
                    "message",
                    "voice_callout",
                    "cooldown_key",
                    "evidence",
                    "metrics",
                ],
                "additionalProperties": False,
            },
        },
        "agent_prompts": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "agent_prompt_specs": {
            "type": "object",
            "additionalProperties": {"type": "object"},
        },
        "agent_context": {
            "type": "object",
            "properties": {
                "focus": {"type": "string"},
                "agent_order": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "active_categories": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "categories": {
                    "type": "object",
                    "additionalProperties": {"type": "object"},
                },
                "review": {"type": "object"},
            },
            "additionalProperties": True,
        },
        "advice_review": {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "accepted_count": {"type": "integer"},
                "rejected_count": {"type": "integer"},
                "rejected_advice_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "issues": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
            "additionalProperties": True,
        },
        "driving_trace": {
            "type": "object",
            "properties": {
                "available": {"type": "boolean"},
                "source": {"type": ["string", "null"]},
                "session_uid": {"type": ["integer", "string", "null"]},
                "session_mismatch": {"type": "boolean"},
                "last_update_timestamp": {"type": ["number", "null"]},
                "age_seconds": {"type": ["number", "null"]},
                "stale": {"type": "boolean"},
                "invalid_payload": {"type": "boolean"},
                "reference_lap_count": {"type": ["integer", "null"]},
                "last_completed_lap": {"type": ["integer", "null"]},
            },
            "additionalProperties": True,
        },
    },
    "required": ["available", "connected", "ok"],
    "additionalProperties": True,
}

# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------

def build_race_engineer_brief(
    telemetry_update: Optional[Dict[str, Any]],
    base_rsp: Dict[str, Any],
    focus: str = _CATEGORY_ALL,
    max_items: int = 5,
    extra_advice: Optional[List[Dict[str, Any]]] = None,
    trace_context: Optional[Dict[str, Any]] = None,
    agent_prompt_overrides: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Build a deterministic race engineer brief from the latest race table snapshot."""
    focus = _normalise_focus(focus)
    max_items = _normalise_max_items(max_items)
    extra_advice_items = _list_of_dicts(extra_advice or [])
    driving_trace = _build_driving_trace_context(trace_context, bool(extra_advice_items))

    if telemetry_update is None:
        if extra_advice_items:
            advice_review = review_race_engineer_advice(extra_advice_items)
            advice = _filter_and_sort_advice(advice_review.accepted_advice, focus, max_items)
            review_summary = advice_review.as_dict()
            return {
                **_dict(base_rsp),
                "available": True,
                "ok": True,
                "status": "ok",
                "error": None,
                "identity": _empty_identity(),
                "progress": _empty_progress(),
                "reference_driver": _empty_reference_driver(),
                "nearby": {"car_ahead": None, "car_behind": None},
                "brief_text": _build_brief_text(advice),
                "advice": advice,
                "agent_prompts": get_agent_prompt_texts(focus, prompt_overrides=agent_prompt_overrides),
                "agent_prompt_specs": get_agent_prompt_specs(focus, prompt_overrides=agent_prompt_overrides),
                "agent_context": _build_agent_context(
                    None,
                    None,
                    {"car_ahead": None, "car_behind": None},
                    focus,
                    advice,
                    review_summary,
                    driving_trace,
                    agent_prompt_overrides,
                ),
                "advice_review": review_summary,
                "driving_trace": driving_trace,
            }
        return base_rsp

    base_rsp = {**_dict(base_rsp)}
    if not isinstance(telemetry_update, dict):
        return {
            **base_rsp,
            "ok": False,
            "status": "error",
            "error": "Telemetry update is not an object.",
            "driving_trace": driving_trace,
        }

    table_entries = _list_of_dicts(telemetry_update.get("table-entries", []))
    if not table_entries:
        return {
            **base_rsp,
            "ok": False,
            "status": "error",
            "error": "No race table entries found in telemetry update.",
            "driving_trace": driving_trace,
        }

    ref_row = _get_ref_row(telemetry_update, table_entries)
    if not ref_row:
        return {
            **base_rsp,
            "ok": False,
            "status": "error",
            "error": "No reference/player row found in telemetry update.",
            "driving_trace": driving_trace,
        }

    base_rsp["ok"] = True
    nearby = _get_nearby_context(table_entries, ref_row)
    advice_review = review_race_engineer_advice([
        *_build_advice(telemetry_update, ref_row, nearby),
        *extra_advice_items,
    ])
    advice = advice_review.accepted_advice
    advice = _filter_and_sort_advice(advice, focus, max_items)
    review_summary = advice_review.as_dict()
    identity = _get_identity(telemetry_update)
    progress = {
        "current_lap": _int_or_none(telemetry_update.get("current-lap")),
        "total_laps": _int_or_none(telemetry_update.get("total-laps")),
        "time_remaining_sec": _num(telemetry_update.get("session-time-left")),
    }
    reference_driver = _get_driver_context(ref_row)

    return {
        **base_rsp,
        "status": "ok",
        "error": None,
        "identity": identity,
        "progress": progress,
        "reference_driver": reference_driver,
        "nearby": nearby,
        "brief_text": _build_brief_text(advice),
        "advice": advice,
        "agent_prompts": get_agent_prompt_texts(focus, prompt_overrides=agent_prompt_overrides),
        "agent_prompt_specs": get_agent_prompt_specs(focus, prompt_overrides=agent_prompt_overrides),
        "agent_context": _build_agent_context(
            telemetry_update,
            ref_row,
            nearby,
            focus,
            advice,
            review_summary,
            driving_trace,
            agent_prompt_overrides,
        ),
        "advice_review": review_summary,
        "driving_trace": driving_trace,
    }


def _normalise_focus(focus: str) -> str:
    if not isinstance(focus, str):
        return _CATEGORY_ALL
    focus = normalise_agent_focus(focus)
    return focus if focus in _VALID_CATEGORIES else _CATEGORY_ALL


def _normalise_max_items(max_items: Any) -> int:
    if isinstance(max_items, bool):
        return 5
    try:
        value = int(max_items)
    except (TypeError, ValueError):
        return 5
    return max(1, min(value, 10))


def _build_driving_trace_context(
    trace_context: Optional[Dict[str, Any]],
    has_advice: bool,
) -> Dict[str, Any]:
    context = _dict(trace_context or {})
    return {
        "available": bool(has_advice or context.get("available")),
        "source": _safe_text(context.get("source")),
        "session_uid": context.get("session_uid"),
        "session_mismatch": bool(context.get("session_mismatch")),
        "last_update_timestamp": _num(context.get("last_update_timestamp")),
        "age_seconds": _num(context.get("age_seconds")),
        "stale": bool(context.get("stale")),
        "invalid_payload": bool(context.get("invalid_payload")),
        "reference_lap_count": _int_or_none(context.get("reference_lap_count")),
        "last_completed_lap": _int_or_none(context.get("last_completed_lap")),
    }


def _build_agent_context(
    telemetry_update: Optional[Dict[str, Any]],
    ref_row: Optional[Dict[str, Any]],
    nearby: Dict[str, Any],
    focus: str,
    accepted_advice: List[Dict[str, Any]],
    review_summary: Dict[str, Any],
    driving_trace: Dict[str, Any],
    agent_prompt_overrides: Optional[Dict[str, Dict[str, str]]],
) -> Dict[str, Any]:
    categories = _selected_agent_context_categories(focus)
    advice_by_category = {
        category: _sort_advice_for_context([
            item for item in accepted_advice if item.get("category") == category
        ])
        for category in categories
    }
    prompt_specs = get_agent_prompt_specs(
        focus,
        include_review=False,
        prompt_overrides=agent_prompt_overrides,
    )

    category_context = {}
    for category in categories:
        facts, missing, metrics = _category_agent_facts(
            category,
            telemetry_update,
            ref_row,
            nearby,
            driving_trace,
        )
        category_advice = advice_by_category.get(category, [])
        category_context[category] = {
            "role": _safe_text(_dict(prompt_specs.get(category, {})).get("role")) or category,
            "status": _agent_category_status(category, category_advice, facts, missing, driving_trace),
            "highest_priority": _highest_priority(category_advice),
            "advice_ids": [str(item.get("id")) for item in category_advice if item.get("id")],
            "next_action": _agent_next_action(category_advice, facts),
            "facts": facts,
            "missing": missing,
            "metrics": metrics,
        }

    agent_order = _agent_order(categories, advice_by_category)
    return {
        "focus": focus,
        "agent_order": agent_order,
        "active_categories": [
            category for category in agent_order if advice_by_category.get(category)
        ],
        "categories": category_context,
        "review": {
            "required": True,
            "accepted_count": review_summary.get("accepted_count", 0),
            "rejected_count": review_summary.get("rejected_count", 0),
            "rejected_advice_ids": review_summary.get("rejected_advice_ids", []),
        },
    }


def _selected_agent_context_categories(focus: str) -> List[str]:
    if focus == _CATEGORY_ALL:
        return list(ADVICE_CATEGORIES)
    if focus in ADVICE_CATEGORIES:
        return [focus]
    return list(ADVICE_CATEGORIES)


def _category_agent_facts(
    category: str,
    telemetry_update: Optional[Dict[str, Any]],
    ref_row: Optional[Dict[str, Any]],
    nearby: Dict[str, Any],
    driving_trace: Dict[str, Any],
) -> tuple[List[str], List[str], Dict[str, Any]]:
    if category == "pace":
        return _pace_agent_facts(ref_row, nearby)
    if category == "tyres":
        return _tyre_agent_facts(telemetry_update, ref_row)
    if category == "fuel":
        return _fuel_agent_facts(ref_row)
    if category == "ers":
        return _ers_agent_facts(ref_row, nearby)
    if category == "damage":
        return _damage_agent_facts(ref_row)
    if category == "weather":
        return _weather_agent_facts(telemetry_update)
    if category == "strategy":
        return _strategy_agent_facts(telemetry_update, ref_row, nearby)
    if category == "race_control":
        return _race_control_agent_facts(telemetry_update, ref_row)
    if category == "driving_coach":
        return _driving_coach_agent_facts(driving_trace)
    return [], ["Unknown race engineer category."], {}


def _pace_agent_facts(
    ref_row: Optional[Dict[str, Any]],
    nearby: Dict[str, Any],
) -> tuple[List[str], List[str], Dict[str, Any]]:
    facts: List[str] = []
    missing: List[str] = []
    metrics: Dict[str, Any] = {}
    if not ref_row:
        return facts, ["Race table snapshot is unavailable."], metrics

    last_lap_ms = _last_lap_ms(ref_row)
    if last_lap_ms is not None:
        facts.append(f"Player last lap: {_format_lap_time_ms(last_lap_ms)}")
        metrics["last_lap_ms"] = last_lap_ms
    else:
        missing.append("Player last completed lap time.")

    curr_lap = _dict(_dict(ref_row.get("lap-info", {})).get("curr-lap", {}))
    current_delta_ms = _num(curr_lap.get("delta-ms"))
    if current_delta_ms is not None:
        delta_word = "up" if current_delta_ms <= 0 else "down"
        facts.append(f"Current lap delta: {delta_word} {_format_gap_ms(abs(current_delta_ms))}")
        metrics["current_delta_ms"] = current_delta_ms
    else:
        missing.append("Current lap delta.")

    worst_sector = _worst_sector_loss(ref_row)
    if worst_sector:
        facts.append(
            f"Worst sector loss: {worst_sector['label']} by {_format_gap_ms(worst_sector['loss_ms'])}"
        )
        metrics["worst_sector"] = worst_sector["key"]
        metrics["worst_sector_loss_ms"] = worst_sector["loss_ms"]
    else:
        missing.append("Comparable last-lap sector times.")

    ahead = nearby.get("car_ahead")
    behind = nearby.get("car_behind")
    if ahead:
        facts.append(
            f"Car ahead: {ahead.get('name') or 'unknown'} at {ahead.get('gap') or 'unknown'}"
        )
        metrics["gap_ahead_ms"] = ahead.get("gap_ms")
        if ahead.get("last_lap"):
            facts.append(f"Car ahead last lap: {ahead['last_lap']}")
    else:
        missing.append("Car ahead context.")

    if behind:
        facts.append(
            f"Car behind: {behind.get('name') or 'unknown'} at {behind.get('gap') or 'unknown'}"
        )
        metrics["gap_behind_ms"] = behind.get("gap_ms")
        if behind.get("last_lap"):
            facts.append(f"Car behind last lap: {behind['last_lap']}")
    else:
        missing.append("Car behind context.")

    return facts, missing, metrics


def _tyre_agent_facts(
    telemetry_update: Optional[Dict[str, Any]],
    ref_row: Optional[Dict[str, Any]],
) -> tuple[List[str], List[str], Dict[str, Any]]:
    facts: List[str] = []
    missing: List[str] = []
    metrics: Dict[str, Any] = {}
    if not ref_row:
        return facts, ["Tyre snapshot is unavailable."], metrics

    tyre = _dict(ref_row.get("tyre-info", {}))
    current = _dict(tyre.get("current-wear", {}))
    compound = _safe_text(tyre.get("visual-tyre-compound"))
    tyre_age = _int_or_none(tyre.get("tyre-age"))
    if compound:
        facts.append(f"Compound: {compound}")
        metrics["compound"] = compound
    else:
        missing.append("Tyre compound.")
    if tyre_age is not None:
        facts.append(f"Tyre age: {tyre_age} laps")
        metrics["tyre_age_laps"] = tyre_age
    else:
        missing.append("Tyre age.")

    avg_wear = _num(current.get("average"))
    if avg_wear is not None:
        facts.append(f"Average wear: {avg_wear:.1f}%")
        metrics["average_wear_pct"] = avg_wear
    wear_values = _tyre_wear_values(current)
    if wear_values:
        worst_tyre, worst_wear = max(wear_values.items(), key=lambda item: item[1])
        facts.append(f"Worst tyre: {_label_tyre(worst_tyre)} at {worst_wear:.1f}%")
        metrics["worst_tyre"] = worst_tyre
        metrics["worst_wear_pct"] = worst_wear
    else:
        missing.append("Per-tyre wear values.")

    prediction = _dict(tyre.get("wear-prediction", {}))
    valid_rates = _tyre_wear_rates(prediction)
    if prediction.get("status") is True and valid_rates:
        fastest_wearing, rate = max(valid_rates.items(), key=lambda item: item[1])
        facts.append(f"Fastest wear rate: {_label_tyre(fastest_wearing)} at {rate:.2f}% per lap")
        metrics["fastest_wear_rate_tyre"] = fastest_wearing
        metrics["fastest_wear_rate_pct_per_lap"] = rate
        forecast = _tyre_stint_forecast(tyre, wear_values)
        if forecast:
            stint_projection = forecast["stint_limit"]
            puncture_projection = forecast["puncture_risk"]
            facts.append(
                f"Projected stint limit: {_label_tyre(stint_projection['tyre'])} to "
                f"{_TYRE_STINT_LIMIT_WEAR_PCT:.0f}% in {stint_projection['laps_to_threshold']:.1f} laps"
            )
            facts.append(
                f"Projected puncture risk: {_label_tyre(puncture_projection['tyre'])} to "
                f"{_TYRE_PUNCTURE_RISK_WEAR_PCT:.0f}% in {puncture_projection['laps_to_threshold']:.1f} laps"
            )
            metrics["projected_stint_limit_tyre"] = stint_projection["tyre"]
            metrics["projected_laps_to_stint_limit"] = stint_projection["laps_to_threshold"]
            metrics["projected_puncture_risk_tyre"] = puncture_projection["tyre"]
            metrics["projected_laps_to_puncture_risk"] = puncture_projection["laps_to_threshold"]
    else:
        missing.append("Reliable wear-rate prediction.")

    compound_analysis = _tyre_compound_analysis(telemetry_update or {}, ref_row)
    fastest_live = compound_analysis.get("fastest_live_compound")
    if fastest_live:
        facts.append(
            f"Fastest live compound: {fastest_live['compound']} via "
            f"{fastest_live.get('driver_name') or 'unknown'} at {_format_lap_time_ms(fastest_live['lap_time_ms'])}"
        )
        metrics["fastest_live_compound"] = fastest_live["compound"]
        metrics["fastest_live_lap_ms"] = fastest_live["lap_time_ms"]
    recommendation = compound_analysis.get("recommendation")
    if recommendation:
        facts.append(
            f"Recommended next tyre: {recommendation['compound']} "
            f"({recommendation['reason']})"
        )
        metrics["recommended_next_compound"] = recommendation["compound"]
        metrics["recommended_next_tyre_source"] = recommendation["source"]

    return facts, missing, metrics


def _fuel_agent_facts(ref_row: Optional[Dict[str, Any]]) -> tuple[List[str], List[str], Dict[str, Any]]:
    facts: List[str] = []
    missing: List[str] = []
    metrics: Dict[str, Any] = {}
    if not ref_row:
        return facts, ["Fuel snapshot is unavailable."], metrics

    fuel = _dict(ref_row.get("fuel-info", {}))
    surplus_live = _num(fuel.get("surplus-laps-png"))
    surplus_game = _num(fuel.get("surplus-laps-game"))
    surplus = surplus_live if surplus_live is not None else surplus_game
    if surplus is not None:
        facts.append(f"Fuel surplus: {surplus:+.2f} laps")
        metrics["surplus_laps"] = surplus
        metrics["surplus_source"] = "png" if surplus_live is not None else "game"
    else:
        missing.append("Fuel surplus estimate.")

    target = _num(fuel.get("target-fuel-rate-next-lap"))
    last_used = _num(fuel.get("last-lap-fuel-used"))
    if target is not None:
        facts.append(f"Target next lap fuel: {target:.2f}kg")
        metrics["target_next_lap_fuel_kg"] = target
    else:
        missing.append("Target next-lap fuel burn.")
    if last_used is not None:
        facts.append(f"Last lap fuel used: {last_used:.2f}kg")
        metrics["last_lap_fuel_used_kg"] = last_used
    else:
        missing.append("Last-lap fuel usage.")
    burn_delta = _fuel_burn_delta_kg(target, last_used)
    if burn_delta is not None:
        direction = "over" if burn_delta > 0 else "under"
        facts.append(f"Last lap fuel burn: {abs(burn_delta):.2f}kg {direction} target")
        metrics["fuel_burn_delta_kg"] = burn_delta

    return facts, missing, metrics


def _ers_agent_facts(
    ref_row: Optional[Dict[str, Any]],
    nearby: Dict[str, Any],
) -> tuple[List[str], List[str], Dict[str, Any]]:
    facts: List[str] = []
    missing: List[str] = []
    metrics: Dict[str, Any] = {}
    if not ref_row:
        return facts, ["ERS snapshot is unavailable."], metrics

    ers = _dict(ref_row.get("ers-info", {}))
    driver = _dict(ref_row.get("driver-info", {}))
    regs_2026 = _dict(ref_row.get("2026-regs-info", {}))
    ers_percent = _num(ers.get("ers-percent-float"))
    ers_mode = _safe_text(ers.get("ers-mode"))
    if ers_percent is not None:
        facts.append(f"ERS battery: {ers_percent:.1f}%")
        metrics["ers_percent"] = ers_percent
    else:
        missing.append("ERS battery percentage.")
    if ers_mode:
        facts.append(f"ERS mode: {ers_mode}")
        metrics["ers_mode"] = ers_mode

    drs_allowed = driver.get("drs-allowed")
    if isinstance(drs_allowed, bool):
        facts.append(f"DRS allowed: {drs_allowed}")
        metrics["drs_allowed"] = drs_allowed
    else:
        missing.append("DRS allowed state.")

    ahead_gap = _num((nearby.get("car_ahead") or {}).get("gap_ms"))
    behind_gap = _num((nearby.get("car_behind") or {}).get("gap_ms"))
    if ahead_gap is not None:
        facts.append(f"Attack gap ahead: {_format_gap_ms(ahead_gap)}")
        metrics["gap_ahead_ms"] = ahead_gap
    if behind_gap is not None:
        facts.append(f"Defence gap behind: {_format_gap_ms(behind_gap)}")
        metrics["gap_behind_ms"] = behind_gap

    overtake_available = regs_2026.get("overtake-avlb")
    if isinstance(overtake_available, bool):
        facts.append(f"Overtake available: {overtake_available}")
        metrics["overtake_available"] = overtake_available

    return facts, missing, metrics


def _damage_agent_facts(ref_row: Optional[Dict[str, Any]]) -> tuple[List[str], List[str], Dict[str, Any]]:
    facts: List[str] = []
    metrics: Dict[str, Any] = {}
    if not ref_row:
        return facts, ["Damage snapshot is unavailable."], metrics

    faults = _damage_faults(ref_row)
    if faults:
        facts.append(f"Faults reported: {', '.join(faults)}")
        metrics["faults"] = faults

    powertrain = _powertrain_damage_parts(ref_row)
    if powertrain:
        worst_powertrain, worst_powertrain_damage = max(powertrain.items(), key=lambda item: item[1])
        facts.append(f"Worst powertrain damage: {worst_powertrain} at {worst_powertrain_damage:.0f}%")
        metrics["worst_powertrain_part"] = worst_powertrain
        metrics["worst_powertrain_damage_pct"] = worst_powertrain_damage

    parts = _damage_parts(ref_row)
    if not parts:
        missing = [] if facts else ["Damage values."]
        return facts, missing, metrics

    worst_part, worst_damage = max(parts.items(), key=lambda item: item[1])
    metrics["worst_part"] = worst_part
    metrics["worst_damage_pct"] = worst_damage
    if worst_damage > 0:
        facts.append(f"Worst damage: {worst_part} at {worst_damage:.0f}%")
    else:
        facts.append("No aero damage reported.")
    return facts, [], metrics


def _weather_agent_facts(
    telemetry_update: Optional[Dict[str, Any]],
) -> tuple[List[str], List[str], Dict[str, Any]]:
    facts: List[str] = []
    missing: List[str] = []
    metrics: Dict[str, Any] = {}
    if not telemetry_update:
        return facts, ["Weather snapshot is unavailable."], metrics

    samples = _weather_samples(telemetry_update)
    if not samples:
        return facts, ["Weather forecast samples."], metrics

    current = _current_weather_sample(samples)
    if current:
        weather = _weather_name(current)
        rain = _rain_percentage(current)
        track_temp = _num(current.get("track-temperature"), _num(telemetry_update.get("track-temperature")))
        air_temp = _num(current.get("air-temperature"), _num(telemetry_update.get("air-temperature")))
        if weather:
            facts.append(f"Current weather: {weather}")
            metrics["current_weather"] = weather
        if rain is not None:
            facts.append(f"Current rain probability: {rain:.0f}%")
            metrics["current_rain_probability_pct"] = rain
        if track_temp is not None:
            facts.append(f"Track temperature: {track_temp:.0f}C")
            metrics["track_temperature_c"] = track_temp
        if air_temp is not None:
            facts.append(f"Air temperature: {air_temp:.0f}C")
            metrics["air_temperature_c"] = air_temp
    else:
        missing.append("Current weather sample.")

    transition = _next_weather_transition(samples)
    if transition:
        facts.append(
            f"Next weather transition: {transition['from_weather']} to {transition['to_weather']} in "
            f"{int(transition['time_offset_min'])} min"
        )
        metrics["next_transition_minutes"] = transition["time_offset_min"]
        metrics["next_transition_to"] = transition["to_weather"]

    rain_risk = _highest_rain_risk(samples, within_minutes=30)
    if rain_risk:
        facts.append(
            f"Highest rain risk next 30 min: {rain_risk['rain_pct']:.0f}% at +{int(rain_risk['time_offset_min'])} min"
        )
        metrics["highest_rain_risk_pct"] = rain_risk["rain_pct"]
        metrics["highest_rain_risk_minutes"] = rain_risk["time_offset_min"]
    else:
        missing.append("Rain probability forecast.")

    temp_shift = _track_temperature_shift(samples, within_minutes=15)
    if temp_shift:
        direction = "up" if temp_shift["delta_c"] > 0 else "down"
        facts.append(
            f"Track temperature trend: {direction} {abs(temp_shift['delta_c']):.0f}C by "
            f"+{int(temp_shift['time_offset_min'])} min"
        )
        metrics["track_temperature_delta_c"] = temp_shift["delta_c"]
        metrics["track_temperature_delta_minutes"] = temp_shift["time_offset_min"]

    return facts, missing, metrics


def _strategy_agent_facts(
    telemetry_update: Optional[Dict[str, Any]],
    ref_row: Optional[Dict[str, Any]],
    nearby: Dict[str, Any],
) -> tuple[List[str], List[str], Dict[str, Any]]:
    facts: List[str] = []
    missing: List[str] = []
    metrics: Dict[str, Any] = {}
    if not telemetry_update:
        return facts, ["Session strategy snapshot is unavailable."], metrics

    current_lap = _num(telemetry_update.get("current-lap"))
    total_laps = _num(telemetry_update.get("total-laps"))
    pit_window = _num(telemetry_update.get("player-pit-window"))
    safety_car_status = _safe_text(telemetry_update.get("safety-car-status"))
    pit_loss_ms = _pit_loss_ms(telemetry_update.get("pit-time-loss"))
    if current_lap is not None:
        if total_laps is not None:
            facts.append(f"Race progress: lap {int(current_lap)} of {int(total_laps)}")
        else:
            facts.append(f"Race progress: lap {int(current_lap)}")
        metrics["current_lap"] = current_lap
        metrics["total_laps"] = total_laps
    else:
        missing.append("Current lap.")
    if pit_window is not None and pit_window > 0:
        facts.append(f"Planned pit window: lap {int(pit_window)}")
        metrics["pit_window"] = pit_window
    else:
        missing.append("Planned pit window.")
    if safety_car_status:
        facts.append(f"Safety car status: {safety_car_status}")
        metrics["safety_car_status"] = safety_car_status
    else:
        missing.append("Safety car status.")
    if pit_loss_ms is not None:
        facts.append(f"Estimated pit loss: {_format_gap_ms(pit_loss_ms)}")
        metrics["pit_loss_ms"] = pit_loss_ms
    else:
        missing.append("Pit loss estimate.")

    if ref_row:
        tyre = _dict(ref_row.get("tyre-info", {}))
        current_wear = _dict(tyre.get("current-wear", {}))
        avg_wear = _num(current_wear.get("average"))
        if avg_wear is not None:
            facts.append(f"Average tyre wear: {avg_wear:.1f}%")
            metrics["average_tyre_wear_pct"] = avg_wear
        compound = _safe_text(tyre.get("visual-tyre-compound"))
        if compound:
            facts.append(f"Current compound: {compound}")
            metrics["compound"] = compound
        player_stops = _int_or_none(tyre.get("num-pitstops"))
        if player_stops is not None:
            facts.append(f"Player pit stops: {player_stops}")
            metrics["player_pit_stops"] = player_stops
        forecast = _tyre_stint_forecast(tyre, _tyre_wear_values(current_wear))
        if forecast:
            stint_projection = forecast["stint_limit"]
            facts.append(
                f"Projected stint limit: {_label_tyre(stint_projection['tyre'])} to "
                f"{_TYRE_STINT_LIMIT_WEAR_PCT:.0f}% in {stint_projection['laps_to_threshold']:.1f} laps"
            )
            metrics["projected_stint_limit_tyre"] = stint_projection["tyre"]
            metrics["projected_laps_to_stint_limit"] = stint_projection["laps_to_threshold"]
        compound_analysis = _tyre_compound_analysis(telemetry_update, ref_row)
        fastest_live = compound_analysis.get("fastest_live_compound")
        if fastest_live:
            facts.append(
                f"Fastest live compound for strategy: {fastest_live['compound']} "
                f"at {_format_lap_time_ms(fastest_live['lap_time_ms'])}"
            )
            metrics["fastest_live_compound"] = fastest_live["compound"]
        recommendation = compound_analysis.get("recommendation")
        if recommendation:
            facts.append(
                f"Recommended next tyre: {recommendation['compound']} "
                f"({recommendation['reason']})"
            )
            metrics["recommended_next_compound"] = recommendation["compound"]
            metrics["recommended_next_tyre_source"] = recommendation["source"]
    gap_behind_ms = _num((nearby.get("car_behind") or {}).get("gap_ms"))
    if gap_behind_ms is not None:
        facts.append(f"Gap behind for pit traffic: {_format_gap_ms(gap_behind_ms)}")
        metrics["gap_behind_ms"] = gap_behind_ms
    ahead = nearby.get("car_ahead") or {}
    behind = nearby.get("car_behind") or {}
    if ahead:
        facts.extend(_nearby_strategy_facts("Car ahead", ahead))
    if behind:
        facts.extend(_nearby_strategy_facts("Car behind", behind))

    weather_samples = _weather_samples(telemetry_update)
    if weather_samples:
        transition = _next_weather_transition(weather_samples)
        if transition:
            facts.append(
                f"Weather transition for strategy: {transition['from_weather']} to "
                f"{transition['to_weather']} in {int(transition['time_offset_min'])} min"
            )
            metrics["weather_transition_minutes"] = transition["time_offset_min"]
            metrics["weather_transition_to"] = transition["to_weather"]
            metrics["weather_transition_to_wet"] = transition["to_wet"]
        rain_risk = _highest_rain_risk(weather_samples, within_minutes=15)
        if rain_risk:
            facts.append(
                f"Rain risk for strategy: {rain_risk['rain_pct']:.0f}% at "
                f"+{int(rain_risk['time_offset_min'])} min"
            )
            metrics["rain_risk_pct"] = rain_risk["rain_pct"]
            metrics["rain_risk_minutes"] = rain_risk["time_offset_min"]
    else:
        missing.append("Weather forecast for strategy.")

    return facts, missing, metrics


def _race_control_agent_facts(
    telemetry_update: Optional[Dict[str, Any]],
    ref_row: Optional[Dict[str, Any]],
) -> tuple[List[str], List[str], Dict[str, Any]]:
    facts: List[str] = []
    missing: List[str] = []
    metrics: Dict[str, Any] = {}
    if not telemetry_update:
        return facts, ["Race control snapshot is unavailable."], metrics

    safety_car_status = _safe_text(telemetry_update.get("safety-car-status"))
    if safety_car_status:
        facts.append(f"Safety car status: {safety_car_status}")
        metrics["safety_car_status"] = safety_car_status
    else:
        missing.append("Safety car status.")
    race_ended = telemetry_update.get("race-ended")
    if isinstance(race_ended, bool):
        facts.append(f"Session ended: {race_ended}")
        metrics["session_ended"] = race_ended

    if ref_row:
        curr_lap = _dict(_dict(ref_row.get("lap-info", {})).get("curr-lap", {}))
        is_valid = curr_lap.get("is-valid")
        if isinstance(is_valid, bool):
            facts.append(f"Current lap valid: {is_valid}")
            metrics["current_lap_valid"] = is_valid
        else:
            missing.append("Current lap validity.")
        warns = _dict(ref_row.get("warns-pens-info", {}))
        warnings = _num(warns.get("corner-cutting-warnings"))
        penalties = _num(warns.get("time-penalties"))
        if warnings is not None:
            facts.append(f"Corner-cutting warnings: {int(warnings)}")
            metrics["corner_cutting_warnings"] = warnings
        if penalties is not None:
            facts.append(f"Time penalties: {int(penalties)}s")
            metrics["time_penalties_sec"] = penalties

    return facts, missing, metrics


def _driving_coach_agent_facts(
    driving_trace: Dict[str, Any],
) -> tuple[List[str], List[str], Dict[str, Any]]:
    facts: List[str] = []
    missing: List[str] = []
    metrics: Dict[str, Any] = {}
    if not driving_trace.get("available"):
        missing.append("Fresh driving trace advice.")
    if driving_trace.get("invalid_payload"):
        facts.append("Trace payload is invalid.")
        metrics["invalid_payload"] = True
    source = _safe_text(driving_trace.get("source"))
    if source:
        facts.append(f"Trace source: {source}")
        metrics["source"] = source
    if driving_trace.get("stale"):
        facts.append("Trace advice is stale.")
        metrics["stale"] = True
    if driving_trace.get("session_mismatch"):
        facts.append("Trace session does not match current race table.")
        metrics["session_mismatch"] = True
    reference_laps = _int_or_none(driving_trace.get("reference_lap_count"))
    if reference_laps is not None:
        facts.append(f"Clean reference laps: {reference_laps}")
        metrics["reference_lap_count"] = reference_laps
    else:
        missing.append("Clean reference lap count.")
    completed_lap = _int_or_none(driving_trace.get("last_completed_lap"))
    if completed_lap is not None:
        facts.append(f"Last analysed lap: {completed_lap}")
        metrics["last_completed_lap"] = completed_lap
    age_seconds = _num(driving_trace.get("age_seconds"))
    if age_seconds is not None:
        facts.append(f"Trace age: {age_seconds:.1f}s")
        metrics["age_seconds"] = age_seconds
    return facts, missing, metrics


def _agent_category_status(
    category: str,
    advice: List[Dict[str, Any]],
    facts: List[str],
    missing: List[str],
    driving_trace: Dict[str, Any],
) -> str:
    if advice:
        return "active_call"
    if category == "driving_coach" and driving_trace.get("stale"):
        return "stale"
    if category == "driving_coach" and driving_trace.get("invalid_payload"):
        return "insufficient_data"
    if facts:
        return "monitoring"
    if missing:
        return "insufficient_data"
    return "monitoring"


def _highest_priority(advice: List[Dict[str, Any]]) -> Optional[str]:
    if not advice:
        return None
    return min(advice, key=lambda item: _PRIORITY_RANK.get(item.get("priority"), 99)).get("priority")


def _agent_next_action(advice: List[Dict[str, Any]], facts: List[str]) -> str:
    if advice:
        return str(advice[0].get("voice_callout") or advice[0].get("message") or "Make the reviewed call.")
    if facts:
        return "Monitor only; no radio call right now."
    return "Wait for stronger telemetry evidence before making a call."


def _agent_order(
    categories: List[str],
    advice_by_category: Dict[str, List[Dict[str, Any]]],
) -> List[str]:
    category_index = {category: index for index, category in enumerate(categories)}
    return sorted(
        categories,
        key=lambda category: (
            _category_priority_rank(advice_by_category.get(category, [])),
            0 if advice_by_category.get(category) else 1,
            category_index.get(category, 99),
        ),
    )


def _category_priority_rank(advice: List[Dict[str, Any]]) -> int:
    if not advice:
        return 99
    return min(_PRIORITY_RANK.get(item.get("priority"), 99) for item in advice)


def _sort_advice_for_context(advice: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        advice,
        key=lambda item: (_PRIORITY_RANK.get(item.get("priority"), 99), item.get("id", "")),
    )


def _empty_identity() -> Dict[str, Any]:
    return {
        "session_uid": None,
        "session_type": None,
        "formula_type": None,
        "circuit_name": None,
        "session_ended": None,
    }


def _empty_progress() -> Dict[str, Any]:
    return {
        "current_lap": None,
        "total_laps": None,
        "time_remaining_sec": None,
    }


def _empty_reference_driver() -> Dict[str, Any]:
    return {
        "driver_index": None,
        "name": None,
        "team": None,
        "position": None,
        "is_player": None,
    }


def _get_identity(telemetry_update: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "session_uid": _int_or_none(telemetry_update.get("session-uid")),
        "session_type": _safe_text(telemetry_update.get("event-type")),
        "formula_type": _safe_text(telemetry_update.get("formula")),
        "circuit_name": _safe_text(telemetry_update.get("circuit")),
        "session_ended": telemetry_update.get("race-ended") if isinstance(telemetry_update.get("race-ended"), bool) else None,
    }


def _get_driver_context(row: Dict[str, Any]) -> Dict[str, Any]:
    driver = _dict(row.get("driver-info", {}))
    return {
        "driver_index": _int_or_none(driver.get("index")),
        "name": _safe_text(driver.get("name")),
        "team": _safe_text(driver.get("team")),
        "position": _int_or_none(driver.get("position")),
        "is_player": driver.get("is-player") if isinstance(driver.get("is-player"), bool) else None,
    }


def _get_ref_row(data: Dict[str, Any], table_entries: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not table_entries:
        return None

    ref_index = data.get("ref-row-index")
    if isinstance(ref_index, int) and not isinstance(ref_index, bool) and 0 <= ref_index < len(table_entries):
        return table_entries[ref_index]

    if data.get("is-spectating", False):
        spectator_index = _int_or_none(data.get("spectator-car-index"))
        if spectator_index is not None:
            return next(
                (
                    row
                    for row in table_entries
                    if _int_or_none(_dict(row.get("driver-info", {})).get("index")) == spectator_index
                ),
                None,
            )

    return next(
        (
            row
            for row in table_entries
            if _dict(row.get("driver-info", {})).get("is-player") is True
        ),
        None,
    )


def _get_nearby_context(
    table_entries: List[Dict[str, Any]],
    ref_row: Dict[str, Any],
) -> Dict[str, Any]:
    sorted_rows = sorted(
        table_entries,
        key=lambda row: _num(_dict(row.get("driver-info", {})).get("position"), default=999),
    )
    ref_position = _num(_dict(ref_row.get("driver-info", {})).get("position"))
    if ref_position is None:
        return {"car_ahead": None, "car_behind": None}

    ref_sorted_index = next((index for index, row in enumerate(sorted_rows) if row is ref_row), None)
    if ref_sorted_index is None:
        return {"car_ahead": None, "car_behind": None}

    car_ahead = sorted_rows[ref_sorted_index - 1] if ref_sorted_index > 0 else None
    car_behind = sorted_rows[ref_sorted_index + 1] if ref_sorted_index + 1 < len(sorted_rows) else None

    gap_ahead_ms = _num(_dict(ref_row.get("delta-info", {})).get("delta-to-car-in-front"))
    gap_behind_ms = (
        _num(_dict(car_behind.get("delta-info", {})).get("delta-to-car-in-front"))
        if car_behind else None
    )

    return {
        "car_ahead": _nearby_driver_context(car_ahead, gap_ahead_ms) if car_ahead else None,
        "car_behind": _nearby_driver_context(car_behind, gap_behind_ms) if car_behind else None,
    }


def _nearby_driver_context(row: Dict[str, Any], gap_ms: Optional[float]) -> Dict[str, Any]:
    driver = _dict(row.get("driver-info", {}))
    lap_info = _dict(row.get("lap-info", {}))
    last_lap = _dict(lap_info.get("last-lap", {}))
    last_lap_ms = _num(last_lap.get("lap-time-ms"))
    tyre = _dict(row.get("tyre-info", {}))
    tyre_wear = _dict(tyre.get("current-wear", {}))
    return {
        "driver_index": _int_or_none(driver.get("index")),
        "name": _safe_text(driver.get("name")),
        "team": _safe_text(driver.get("team")),
        "position": _int_or_none(driver.get("position")),
        "gap_ms": gap_ms,
        "gap": _format_gap_ms(gap_ms),
        "last_lap_ms": last_lap_ms,
        "last_lap": _format_lap_time_ms(last_lap_ms),
        "compound": _safe_text(tyre.get("visual-tyre-compound")),
        "tyre_age_laps": _int_or_none(tyre.get("tyre-age")),
        "average_tyre_wear_pct": _num(tyre_wear.get("average")),
        "num_pitstops": _int_or_none(tyre.get("num-pitstops")),
    }


def _build_advice(
    telemetry_update: Dict[str, Any],
    ref_row: Dict[str, Any],
    nearby: Dict[str, Any],
) -> List[Dict[str, Any]]:
    advice: List[Dict[str, Any]] = []
    advice.extend(_race_control_advice(telemetry_update, ref_row))
    advice.extend(_pace_advice(ref_row, nearby))
    advice.extend(_tyre_advice(telemetry_update, ref_row))
    advice.extend(_fuel_advice(ref_row))
    advice.extend(_ers_advice(ref_row, nearby))
    advice.extend(_damage_advice(ref_row))
    advice.extend(_weather_advice(telemetry_update))
    advice.extend(_strategy_advice(telemetry_update, ref_row, nearby))
    return advice


def _race_control_advice(telemetry_update: Dict[str, Any], ref_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    advice: List[Dict[str, Any]] = []

    safety_car_status = _safe_text(telemetry_update.get("safety-car-status"))
    if safety_car_status and safety_car_status.lower() not in {"none", "no safety car", "safety_car_status.none"}:
        advice.append(_item(
            item_id="race-control-safety-car",
            category="race_control",
            priority="warning",
            title="Race control status",
            message=f"Race control reports {safety_car_status}. Keep the car clean and watch for strategy changes.",
            voice_callout=f"Race control: {safety_car_status}. Keep it clean.",
            cooldown_key="race_control:safety_car",
            evidence=[f"safety-car-status={safety_car_status}"],
            metrics={"safety_car_status": safety_car_status},
        ))

    curr_lap = _dict(_dict(ref_row.get("lap-info", {})).get("curr-lap", {}))
    if curr_lap.get("is-valid") is False:
        advice.append(_item(
            item_id="race-control-invalid-lap",
            category="race_control",
            priority="advisory",
            title="Current lap invalid",
            message="This lap is currently invalid, so use it for recovery or tyre/battery management.",
            voice_callout="Current lap invalid. Use this lap to reset.",
            cooldown_key="race_control:invalid_lap",
            evidence=["lap-info.curr-lap.is-valid=false"],
            metrics={},
        ))

    warns = _dict(ref_row.get("warns-pens-info", {}))
    corner_warnings = _num(warns.get("corner-cutting-warnings"))
    penalties = _num(warns.get("time-penalties"))
    if corner_warnings is not None and corner_warnings >= 2:
        advice.append(_item(
            item_id="race-control-corner-warnings",
            category="race_control",
            priority="warning",
            title="Track limits risk",
            message=f"You have {int(corner_warnings)} corner-cutting warnings. Prioritise clean exits.",
            voice_callout=f"Track limits risk. {int(corner_warnings)} warnings.",
            cooldown_key="race_control:corner_warnings",
            evidence=[f"corner-cutting-warnings={int(corner_warnings)}"],
            metrics={"corner_cutting_warnings": corner_warnings},
        ))
    if penalties is not None and penalties > 0:
        advice.append(_item(
            item_id="race-control-penalties",
            category="race_control",
            priority="warning",
            title="Time penalty active",
            message=f"You have {int(penalties)} seconds of penalties. Build the gap before the finish.",
            voice_callout=f"{int(penalties)} seconds of penalties. Build the gap.",
            cooldown_key="race_control:penalties",
            evidence=[f"time-penalties={int(penalties)}"],
            metrics={"time_penalties_sec": penalties},
        ))

    return advice


def _pace_advice(ref_row: Dict[str, Any], nearby: Dict[str, Any]) -> List[Dict[str, Any]]:
    advice: List[Dict[str, Any]] = []
    ref_lap = _last_lap_ms(ref_row)
    ahead = nearby.get("car_ahead")
    behind = nearby.get("car_behind")
    battle_target = None

    battle_advice = _battle_pace_advice(ref_lap, ahead, behind)
    if battle_advice:
        advice.append(battle_advice)
        battle_target = battle_advice["metrics"].get("battle_target")

    if ahead and ref_lap and battle_target != "ahead":
        ahead_row_lap = _nearby_last_lap_ms(ahead)
        if ahead_row_lap:
            diff_ms = ref_lap - ahead_row_lap
            if diff_ms <= -250:
                advice.append(_item(
                    item_id="pace-catching-ahead",
                    category="pace",
                    priority="advisory",
                    title="Catching the car ahead",
                    message=(
                        f"You were {_format_gap_ms(abs(diff_ms))} faster than {ahead['name']} last lap. "
                        f"Gap ahead is {ahead['gap']}."
                    ),
                    voice_callout=f"Good pace. You were {_format_gap_ms(abs(diff_ms))} faster than the car ahead.",
                    cooldown_key="pace:catching_ahead",
                    evidence=[
                        f"player-last-lap={_format_lap_time_ms(ref_lap)}",
                        f"car-ahead-last-lap={ahead['last_lap']}",
                        f"gap-ahead={ahead['gap']}",
                    ],
                    metrics={"last_lap_delta_to_ahead_ms": diff_ms, "gap_ahead_ms": ahead.get("gap_ms")},
                ))
            elif diff_ms >= 500:
                advice.append(_item(
                    item_id="pace-losing-ahead",
                    category="pace",
                    priority="info",
                    title="Pace gap to car ahead",
                    message=(
                        f"{ahead['name']} was {_format_gap_ms(diff_ms)} faster last lap. "
                        "Focus on exits before using battery to attack."
                    ),
                    voice_callout=f"Car ahead is {_format_gap_ms(diff_ms)} quicker. Focus on exits.",
                    cooldown_key="pace:losing_ahead",
                    evidence=[
                        f"player-last-lap={_format_lap_time_ms(ref_lap)}",
                        f"car-ahead-last-lap={ahead['last_lap']}",
                    ],
                    metrics={"last_lap_delta_to_ahead_ms": diff_ms},
                ))

    if behind and ref_lap and battle_target != "behind":
        behind_lap = _nearby_last_lap_ms(behind)
        if behind_lap:
            diff_ms = ref_lap - behind_lap
            if diff_ms >= 500:
                advice.append(_item(
                    item_id="pace-threat-behind",
                    category="pace",
                    priority="warning",
                    title="Car behind has pace",
                    message=(
                        f"{behind['name']} was {_format_gap_ms(diff_ms)} faster last lap. "
                        f"Gap behind is {behind['gap']}."
                    ),
                    voice_callout=f"Car behind is faster. Gap {behind['gap']}.",
                    cooldown_key="pace:threat_behind",
                    evidence=[
                        f"player-last-lap={_format_lap_time_ms(ref_lap)}",
                        f"car-behind-last-lap={behind['last_lap']}",
                        f"gap-behind={behind['gap']}",
                    ],
                    metrics={"last_lap_delta_to_behind_ms": diff_ms, "gap_behind_ms": behind.get("gap_ms")},
                ))

    if not advice:
        sector_advice = _sector_loss_advice(ref_row)
        if sector_advice:
            advice.append(sector_advice)

    if not advice:
        lap_info = _dict(ref_row.get("lap-info", {}))
        curr_lap = _dict(lap_info.get("curr-lap", {}))
        delta_ms = _num(curr_lap.get("delta-ms"))
        if delta_ms is not None:
            priority = "advisory" if delta_ms <= 0 else "info"
            adjective = "up" if delta_ms <= 0 else "down"
            advice.append(_item(
                item_id="pace-current-delta",
                category="pace",
                priority=priority,
                title="Current lap delta",
                message=f"You are {adjective} against your reference by {_format_gap_ms(abs(delta_ms))}.",
                voice_callout=f"Current delta {adjective} {_format_gap_ms(abs(delta_ms))}.",
                cooldown_key="pace:current_delta",
                evidence=[f"lap-info.curr-lap.delta-ms={_format_gap_ms(delta_ms)}"],
                metrics={"current_delta_ms": delta_ms},
            ))

    return advice


def _battle_pace_advice(
    ref_lap: Optional[float],
    ahead: Optional[Dict[str, Any]],
    behind: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return one short attack/defence call for a live DRS battle."""

    if not ref_lap:
        return None

    behind_gap = _num((behind or {}).get("gap_ms"))
    behind_lap = _nearby_last_lap_ms(behind or {})
    if behind and behind_gap is not None and 0 < behind_gap <= _DRS_BATTLE_GAP_MS and behind_lap:
        diff_ms = ref_lap - behind_lap
        if diff_ms >= _BATTLE_PACE_DELTA_MS:
            return _item(
                item_id="pace-battle-defend-drs",
                category="pace",
                priority="warning",
                title="Defend DRS battle",
                message=(
                    f"{behind.get('name') or 'Car behind'} is within DRS at {_format_gap_ms(behind_gap)} "
                    f"and was {_format_gap_ms(diff_ms)} faster last lap. "
                    "Prioritise exits and keep the inside covered."
                ),
                voice_callout=(
                    f"Defend. Car behind in DRS and quicker by {_format_gap_ms(diff_ms)}. "
                    "Prioritise exit traction."
                ),
                cooldown_key="pace:battle:defend_drs",
                evidence=[
                    f"gap-behind={_format_gap_ms(behind_gap)}",
                    f"player-last-lap={_format_lap_time_ms(ref_lap)}",
                    f"car-behind-last-lap={behind.get('last_lap')}",
                ],
                metrics={
                    "battle_target": "behind",
                    "gap_behind_ms": behind_gap,
                    "last_lap_delta_to_behind_ms": diff_ms,
                },
            )

    ahead_gap = _num((ahead or {}).get("gap_ms"))
    ahead_lap = _nearby_last_lap_ms(ahead or {})
    if ahead and ahead_gap is not None and 0 < ahead_gap <= _DRS_BATTLE_GAP_MS and ahead_lap:
        diff_ms = ref_lap - ahead_lap
        if diff_ms <= _BATTLE_PACE_DELTA_MS:
            if diff_ms <= -_BATTLE_PACE_DELTA_MS:
                pace_text = f"You were {_format_gap_ms(abs(diff_ms))} faster last lap."
                voice_pace = f"You were {_format_gap_ms(abs(diff_ms))} faster."
            else:
                pace_text = "Your last-lap pace is close enough to attack."
                voice_pace = "Pace is close enough."
            return _item(
                item_id="pace-battle-attack-drs",
                category="pace",
                priority="advisory",
                title="Attack DRS battle",
                message=(
                    f"{ahead.get('name') or 'Car ahead'} is within DRS at {_format_gap_ms(ahead_gap)}. "
                    f"{pace_text} Prepare the exit before the straight."
                ),
                voice_callout=(
                    f"Attack window. Car ahead in DRS. {voice_pace} Set up the exit."
                ),
                cooldown_key="pace:battle:attack_drs",
                evidence=[
                    f"gap-ahead={_format_gap_ms(ahead_gap)}",
                    f"player-last-lap={_format_lap_time_ms(ref_lap)}",
                    f"car-ahead-last-lap={ahead.get('last_lap')}",
                ],
                metrics={
                    "battle_target": "ahead",
                    "gap_ahead_ms": ahead_gap,
                    "last_lap_delta_to_ahead_ms": diff_ms,
                },
            )

    return None


def _tyre_advice(
    telemetry_update: Dict[str, Any],
    ref_row: Dict[str, Any],
) -> List[Dict[str, Any]]:
    tyre = _dict(ref_row.get("tyre-info", {}))
    current = _dict(tyre.get("current-wear", {}))
    available_wear = _tyre_wear_values(current)
    advice: List[Dict[str, Any]] = []
    compound = _safe_text(tyre.get("visual-tyre-compound"))
    tyre_age = tyre.get("tyre-age")
    if available_wear:
        worst_name, worst_value = max(available_wear.items(), key=lambda item: item[1])

        if worst_value >= 80:
            priority = "critical"
            message = f"{_label_tyre(worst_name)} tyre wear is {worst_value:.1f}%. Puncture risk is high."
            voice = f"Tyre warning. {_label_tyre(worst_name)} is at {worst_value:.0f} percent."
        elif worst_value >= 70:
            priority = "warning"
            message = f"{_label_tyre(worst_name)} tyre wear is {worst_value:.1f}%. Manage sliding and traction."
            voice = f"Tyres are high. {_label_tyre(worst_name)} at {worst_value:.0f} percent."
        elif worst_value >= 60:
            priority = "advisory"
            message = f"{_label_tyre(worst_name)} tyre wear is {worst_value:.1f}%. Keep exits clean."
            voice = f"Tyres are getting worn. {_label_tyre(worst_name)} at {worst_value:.0f} percent."
        else:
            priority = None
            message = ""
            voice = ""

        if priority:
            evidence = [
                f"compound={compound}",
                f"tyre-age-laps={tyre_age}",
                f"{worst_name}-wear={worst_value:.1f}%",
            ]
            advice.append(_item(
                item_id="tyres-wear",
                category="tyres",
                priority=priority,
                title="Tyre wear",
                message=message,
                voice_callout=voice,
                cooldown_key=f"tyres:wear:{worst_name}",
                evidence=evidence,
                metrics={"worst_tyre": worst_name, "worst_wear_pct": worst_value},
            ))

    forecast_advice = _tyre_stint_forecast_advice(tyre, compound, tyre_age, available_wear)
    if forecast_advice:
        advice.append(forecast_advice)

    rate_advice = _tyre_wear_rate_advice(tyre, compound, tyre_age)
    if rate_advice:
        advice.append(rate_advice)

    compound_advice = _tyre_compound_pace_advice(telemetry_update, ref_row)
    if compound_advice:
        advice.append(compound_advice)

    return advice


def _fuel_advice(ref_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    fuel = _dict(ref_row.get("fuel-info", {}))
    surplus_live = _num(fuel.get("surplus-laps-png"))
    surplus_game = _num(fuel.get("surplus-laps-game"))
    surplus = surplus_live if surplus_live is not None else surplus_game

    if surplus is None:
        return []

    target = _num(fuel.get("target-fuel-rate-next-lap"))
    last_used = _num(fuel.get("last-lap-fuel-used"))
    evidence = [f"surplus-laps={surplus:.2f}"]
    if target:
        evidence.append(f"target-next-lap-fuel={target:.2f}kg")
    if last_used:
        evidence.append(f"last-lap-fuel-used={last_used:.2f}kg")

    if surplus <= -0.5:
        return [_item(
            item_id="fuel-critical-deficit",
            category="fuel",
            priority="critical",
            title="Fuel deficit",
            message=f"Fuel is {abs(surplus):.2f} laps short. Lift and coast until the deficit stabilises.",
            voice_callout=f"Fuel critical. Minus {abs(surplus):.1f} laps. Lift and coast.",
            cooldown_key="fuel:deficit:critical",
            evidence=evidence,
            metrics={"surplus_laps": surplus, "target_next_lap_fuel_kg": target},
        )]

    if surplus <= -0.1:
        return [_item(
            item_id="fuel-small-deficit",
            category="fuel",
            priority="warning",
            title="Fuel saving needed",
            message=f"Fuel is {abs(surplus):.2f} laps short. Add lift and coast on the biggest braking zones.",
            voice_callout=f"Fuel minus {abs(surplus):.1f}. Start saving.",
            cooldown_key="fuel:deficit:warning",
            evidence=evidence,
            metrics={"surplus_laps": surplus, "target_next_lap_fuel_kg": target},
        )]

    burn_delta = _fuel_burn_delta_kg(target, last_used)
    if burn_delta is not None and burn_delta >= 0.12 and surplus <= 0.25:
        priority = "warning" if surplus <= 0.1 or burn_delta >= 0.2 else "advisory"
        return [_item(
            item_id="fuel-over-target",
            category="fuel",
            priority=priority,
            title="Fuel burn above target",
            message=(
                f"Last lap fuel burn was {burn_delta:.2f}kg over target with only "
                f"{surplus:+.2f} laps in hand. Add a short lift and coast phase."
            ),
            voice_callout="Fuel burn is over target. Add a short lift and coast.",
            cooldown_key="fuel:over_target",
            evidence=evidence + [f"fuel-burn-delta={burn_delta:.2f}kg"],
            metrics={
                "surplus_laps": surplus,
                "target_next_lap_fuel_kg": target,
                "last_lap_fuel_used_kg": last_used,
                "fuel_burn_delta_kg": burn_delta,
            },
        )]

    if surplus >= 0.5:
        return [_item(
            item_id="fuel-surplus",
            category="fuel",
            priority="info",
            title="Fuel surplus",
            message=f"Fuel is plus {surplus:.2f} laps. You have room to push if tyres and ERS allow it.",
            voice_callout=f"Fuel plus {surplus:.1f}. You can push if needed.",
            cooldown_key="fuel:surplus",
            evidence=evidence,
            metrics={"surplus_laps": surplus, "target_next_lap_fuel_kg": target},
        )]

    return []


def _ers_advice(ref_row: Dict[str, Any], nearby: Dict[str, Any]) -> List[Dict[str, Any]]:
    ers = _dict(ref_row.get("ers-info", {}))
    regs_2026 = _dict(ref_row.get("2026-regs-info", {}))
    ers_percent = _num(ers.get("ers-percent-float"))
    if ers_percent is None:
        return []

    behind_gap = _num((nearby.get("car_behind") or {}).get("gap_ms"))
    ahead_gap = _num((nearby.get("car_ahead") or {}).get("gap_ms"))

    if behind_gap is not None and 0 < behind_gap <= 1000 and ers_percent <= 15:
        return [_item(
            item_id="ers-defend-low-battery",
            category="ers",
            priority="warning",
            title="Defend with low battery",
            message=(
                f"Car behind is within DRS at {_format_gap_ms(behind_gap)}, "
                f"but ERS is only {ers_percent:.1f}%. Prioritise exits and harvest where safe."
            ),
            voice_callout="Car behind in DRS and battery is low. Prioritise exit and harvest.",
            cooldown_key="ers:defend_low_battery",
            evidence=[f"gap-behind={_format_gap_ms(behind_gap)}", f"ers={ers_percent:.1f}%"],
            metrics={"ers_percent": ers_percent, "gap_behind_ms": behind_gap},
        )]

    if behind_gap is not None and 0 < behind_gap <= 1000:
        return [_item(
            item_id="ers-defend-drs",
            category="ers",
            priority="warning",
            title="Defend DRS",
            message=f"Car behind is within DRS at {_format_gap_ms(behind_gap)}. Keep battery for defence.",
            voice_callout=f"Car behind in DRS. Save battery to defend.",
            cooldown_key="ers:defend_drs",
            evidence=[f"gap-behind={_format_gap_ms(behind_gap)}", f"ers={ers_percent:.1f}%"],
            metrics={"ers_percent": ers_percent, "gap_behind_ms": behind_gap},
        )]

    if ahead_gap is not None and 0 < ahead_gap <= 1000 and ers_percent < 25:
        return [_item(
            item_id="ers-attack-harvest",
            category="ers",
            priority="advisory",
            title="Attack window with low battery",
            message=(
                f"Car ahead is within DRS at {_format_gap_ms(ahead_gap)}, "
                f"but ERS is {ers_percent:.1f}%. Harvest before committing to the attack."
            ),
            voice_callout="Car ahead in DRS, but battery is low. Harvest before attacking.",
            cooldown_key="ers:attack_harvest",
            evidence=[f"gap-ahead={_format_gap_ms(ahead_gap)}", f"ers={ers_percent:.1f}%"],
            metrics={"ers_percent": ers_percent, "gap_ahead_ms": ahead_gap},
        )]

    if ahead_gap is not None and 0 < ahead_gap <= 1000 and ers_percent >= 25:
        return [_item(
            item_id="ers-attack-drs",
            category="ers",
            priority="advisory",
            title="Attack window",
            message=f"Car ahead is within DRS at {_format_gap_ms(ahead_gap)}. Battery is {ers_percent:.1f}%.",
            voice_callout=f"Attack window. Car ahead in DRS.",
            cooldown_key="ers:attack_drs",
            evidence=[f"gap-ahead={_format_gap_ms(ahead_gap)}", f"ers={ers_percent:.1f}%"],
            metrics={"ers_percent": ers_percent, "gap_ahead_ms": ahead_gap},
        )]

    overtake_available = regs_2026.get("overtake-avlb")
    overtake_distance = _num(regs_2026.get("overtake-dist"))
    if overtake_available is True:
        return [_item(
            item_id="ers-overtake-available",
            category="ers",
            priority="advisory",
            title="Overtake available",
            message="Overtake mode is available. Use it only with a clear attack or defence target.",
            voice_callout="Overtake available.",
            cooldown_key="ers:overtake_available",
            evidence=[f"overtake-dist={overtake_distance}"],
            metrics={"ers_percent": ers_percent, "overtake_distance_m": overtake_distance},
        )]

    if ers_percent <= 15:
        return [_item(
            item_id="ers-low",
            category="ers",
            priority="advisory",
            title="Low battery",
            message=f"ERS is {ers_percent:.1f}%. Recover before attacking.",
            voice_callout=f"Battery low. ERS {ers_percent:.0f} percent.",
            cooldown_key="ers:low",
            evidence=[f"ers={ers_percent:.1f}%"],
            metrics={"ers_percent": ers_percent},
        )]

    return []


def _damage_advice(ref_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    critical_fault = _damage_fault_advice(ref_row)
    if critical_fault:
        return [critical_fault]

    powertrain_advice = _powertrain_damage_advice(ref_row)
    if powertrain_advice:
        return [powertrain_advice]

    parts = _damage_parts(ref_row)
    if not parts:
        return []

    worst_part, worst_damage = max(parts.items(), key=lambda item: item[1])
    if worst_damage >= 25:
        priority = "critical"
        message = f"{worst_part.title()} damage is {worst_damage:.0f}%. Consider boxing if pace loss is severe."
        voice = f"Damage warning. {worst_part} at {worst_damage:.0f} percent."
    elif worst_damage >= 10:
        priority = "warning"
        message = f"{worst_part.title()} damage is {worst_damage:.0f}%. Expect weaker balance."
        voice = f"{worst_part} damage at {worst_damage:.0f} percent."
    else:
        return []

    return [_item(
        item_id="damage-aero",
        category="damage",
        priority=priority,
        title="Car damage",
        message=message,
        voice_callout=voice,
        cooldown_key=f"damage:{worst_part.replace(' ', '_')}",
        evidence=[f"{worst_part}={worst_damage:.0f}%"],
        metrics={"worst_part": worst_part, "worst_damage_pct": worst_damage},
    )]


def _weather_advice(telemetry_update: Dict[str, Any]) -> List[Dict[str, Any]]:
    samples = _weather_samples(telemetry_update)
    if not samples:
        return []

    current = _current_weather_sample(samples)
    current_weather = _weather_name(current) if current else None
    current_track_temp = _num(
        current.get("track-temperature") if current else None,
        _num(telemetry_update.get("track-temperature")),
    )

    transition = _next_weather_transition(samples)
    if transition and transition["to_wet"] and not transition["from_wet"] and transition["time_offset_min"] <= 20:
        minutes = int(transition["time_offset_min"])
        rain_pct = _num(transition.get("rain_pct"))
        priority = "warning" if minutes <= 10 or (rain_pct is not None and rain_pct >= 50) else "advisory"
        return [_item(
            item_id="weather-rain-arriving",
            category="weather",
            priority=priority,
            title="Rain arriving",
            message=(
                f"Forecast shifts from {transition['from_weather']} to {transition['to_weather']} in "
                f"{minutes} minutes. Prepare the tyre call and avoid overheating the dry tyres."
            ),
            voice_callout=f"Rain expected in {minutes} minutes. Be ready for the tyre call.",
            cooldown_key=f"weather:rain_arriving:{minutes}",
            evidence=[
                f"current-weather={transition['from_weather']}",
                f"forecast-weather={transition['to_weather']}",
                f"time-offset-min={minutes}",
                f"rain-probability={rain_pct:.0f}%" if rain_pct is not None else "rain-probability=unavailable",
            ],
            metrics={
                "time_offset_min": transition["time_offset_min"],
                "rain_probability_pct": rain_pct,
                "from_weather": transition["from_weather"],
                "to_weather": transition["to_weather"],
            },
        )]

    if transition and transition["from_wet"] and not transition["to_wet"] and transition["time_offset_min"] <= 20:
        minutes = int(transition["time_offset_min"])
        return [_item(
            item_id="weather-drying-window",
            category="weather",
            priority="advisory",
            title="Drying window",
            message=(
                f"Forecast moves from {transition['from_weather']} to {transition['to_weather']} in "
                f"{minutes} minutes. Watch for the crossover before committing to another wet stint."
            ),
            voice_callout=f"Drying trend in {minutes} minutes. Watch the crossover.",
            cooldown_key=f"weather:drying_window:{minutes}",
            evidence=[
                f"current-weather={transition['from_weather']}",
                f"forecast-weather={transition['to_weather']}",
                f"time-offset-min={minutes}",
            ],
            metrics={
                "time_offset_min": transition["time_offset_min"],
                "from_weather": transition["from_weather"],
                "to_weather": transition["to_weather"],
            },
        )]

    rain_risk = _highest_rain_risk(samples, within_minutes=15)
    if rain_risk and not _is_wet_weather(current_weather) and rain_risk["rain_pct"] >= 60:
        minutes = int(rain_risk["time_offset_min"])
        return [_item(
            item_id="weather-rain-risk",
            category="weather",
            priority="advisory",
            title="Rain risk rising",
            message=(
                f"Rain probability reaches {rain_risk['rain_pct']:.0f}% in {minutes} minutes. "
                "Keep the stint flexible."
            ),
            voice_callout=f"Rain risk {rain_risk['rain_pct']:.0f} percent in {minutes} minutes.",
            cooldown_key=f"weather:rain_risk:{minutes}",
            evidence=[
                f"rain-probability={rain_risk['rain_pct']:.0f}%",
                f"time-offset-min={minutes}",
                f"forecast-weather={rain_risk.get('weather') or 'unknown'}",
            ],
            metrics={
                "rain_probability_pct": rain_risk["rain_pct"],
                "time_offset_min": rain_risk["time_offset_min"],
                "weather": rain_risk.get("weather"),
            },
        )]

    temp_shift = _track_temperature_shift(samples, within_minutes=15)
    if temp_shift and abs(temp_shift["delta_c"]) >= 4:
        direction = "rising" if temp_shift["delta_c"] > 0 else "falling"
        action = "Expect more thermal stress and manage sliding." if temp_shift["delta_c"] > 0 \
            else "Expect lower grip and warm the tyres carefully."
        minutes = int(temp_shift["time_offset_min"])
        return [_item(
            item_id="weather-track-temp-shift",
            category="weather",
            priority="info",
            title="Track temperature shift",
            message=(
                f"Track temperature is {direction} by {abs(temp_shift['delta_c']):.0f}C over the next "
                f"{minutes} minutes. {action}"
            ),
            voice_callout=(
                f"Track temperature {direction}. "
                f"{'Manage sliding.' if temp_shift['delta_c'] > 0 else 'Warm the tyres carefully.'}"
            ),
            cooldown_key=f"weather:track_temp:{direction}",
            evidence=[
                f"current-track-temperature={current_track_temp:.0f}C" if current_track_temp is not None
                else "current-track-temperature=unavailable",
                f"forecast-track-temperature={temp_shift['future_temp_c']:.0f}C",
                f"time-offset-min={minutes}",
            ],
            metrics={
                "track_temperature_delta_c": temp_shift["delta_c"],
                "current_track_temperature_c": current_track_temp,
                "future_track_temperature_c": temp_shift["future_temp_c"],
                "time_offset_min": temp_shift["time_offset_min"],
            },
        )]

    if current_track_temp is not None and current_track_temp >= 45 and not _is_wet_weather(current_weather):
        return [_item(
            item_id="weather-hot-track",
            category="weather",
            priority="info",
            title="Hot track",
            message=(
                f"Track temperature is {current_track_temp:.0f}C. Rear overheating and traction loss are more likely."
            ),
            voice_callout=f"Hot track, {current_track_temp:.0f} degrees. Manage rear sliding.",
            cooldown_key="weather:hot_track",
            evidence=[f"track-temperature={current_track_temp:.0f}C"],
            metrics={"track_temperature_c": current_track_temp},
        )]

    return []


def _damage_fault_advice(ref_row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    damage = _dict(ref_row.get("damage-info", {}))
    if damage.get("engine-blown") is True:
        return _item(
            item_id="damage-engine-blown",
            category="damage",
            priority="critical",
            title="Engine failure",
            message="Engine failure reported. Bring the car home safely if it is still moving.",
            voice_callout="Engine failure. Bring the car home safely.",
            cooldown_key="damage:engine_blown",
            evidence=["engine-blown=true"],
            metrics={"engine_blown": True},
        )
    if damage.get("engine-seized") is True:
        return _item(
            item_id="damage-engine-seized",
            category="damage",
            priority="critical",
            title="Engine seized",
            message="Engine seized reported. Move off the racing line if possible.",
            voice_callout="Engine seized. Move off the racing line if possible.",
            cooldown_key="damage:engine_seized",
            evidence=["engine-seized=true"],
            metrics={"engine_seized": True},
        )
    if damage.get("ers-fault") is True:
        return _item(
            item_id="damage-ers-fault",
            category="damage",
            priority="warning",
            title="ERS fault",
            message="ERS fault reported. Expect weaker deployment and defend with exits rather than battery.",
            voice_callout="ERS fault. Defend with exits, not battery.",
            cooldown_key="damage:ers_fault",
            evidence=["ers-fault=true"],
            metrics={"ers_fault": True},
        )
    if damage.get("drs-fault") is True:
        return _item(
            item_id="damage-drs-fault",
            category="damage",
            priority="warning",
            title="DRS fault",
            message="DRS fault reported. Plan overtakes without relying on DRS.",
            voice_callout="DRS fault. Plan overtakes without DRS.",
            cooldown_key="damage:drs_fault",
            evidence=["drs-fault=true"],
            metrics={"drs_fault": True},
        )
    return None


def _powertrain_damage_advice(ref_row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    parts = _powertrain_damage_parts(ref_row)
    if not parts:
        return None

    worst_part, worst_damage = max(parts.items(), key=lambda item: item[1])
    if worst_damage >= 70:
        priority = "critical"
        action = "Short-shift and avoid unnecessary kerbs."
    elif worst_damage >= 50:
        priority = "warning"
        action = "Short-shift and avoid over-revving."
    else:
        return None

    label = worst_part.replace("-", " ")
    return _item(
        item_id=f"damage-powertrain-{worst_part}",
        category="damage",
        priority=priority,
        title="Powertrain wear",
        message=f"{label.title()} damage is {worst_damage:.0f}%. {action}",
        voice_callout=f"{label.title()} damage high. Short-shift where possible.",
        cooldown_key=f"damage:powertrain:{worst_part}",
        evidence=[f"{worst_part}={worst_damage:.0f}%"],
        metrics={"worst_part": worst_part, "worst_damage_pct": worst_damage},
    )


def _strategy_advice(
    telemetry_update: Dict[str, Any],
    ref_row: Dict[str, Any],
    nearby: Dict[str, Any],
) -> List[Dict[str, Any]]:
    current_lap = _num(telemetry_update.get("current-lap"))
    pit_window = _num(telemetry_update.get("player-pit-window"))
    if current_lap is None or pit_window is None or pit_window <= 0:
        return []

    tyre = _dict(ref_row.get("tyre-info", {}))
    avg_wear = _num(_dict(tyre.get("current-wear", {})).get("average"))
    compound = _safe_text(tyre.get("visual-tyre-compound"))
    safety_car_status = _safe_text(telemetry_update.get("safety-car-status"))
    safety_car_active = _is_safety_car_active(safety_car_status)
    gap_behind_ms = _num((nearby.get("car_behind") or {}).get("gap_ms"))
    pit_loss_ms = _pit_loss_ms(telemetry_update.get("pit-time-loss"))
    traffic_risk = (
        gap_behind_ms is not None
        and pit_loss_ms is not None
        and gap_behind_ms < pit_loss_ms
    )
    compound_analysis = _tyre_compound_analysis(telemetry_update, ref_row)
    tyre_choice = compound_analysis.get("recommendation")
    choice_message = _tyre_choice_message_suffix(tyre_choice)
    choice_voice = _tyre_choice_voice_suffix(tyre_choice)
    choice_evidence = _tyre_choice_evidence(tyre_choice)
    choice_metrics = _tyre_choice_metrics(tyre_choice)

    if safety_car_active and current_lap >= pit_window - 1 and avg_wear is not None and avg_wear >= 30:
        return [_item(
            item_id="strategy-safety-car-box",
            category="strategy",
            priority="warning",
            title="Safety car pit opportunity",
            message=(
                f"{safety_car_status} is active near the planned pit window on lap {int(current_lap)}. "
                f"Current {compound} wear averages {avg_wear:.1f}%.{choice_message}"
            ),
            voice_callout=f"Safety car window. Consider boxing if pit entry is open.{choice_voice}",
            cooldown_key=f"strategy:safety_car_box:{int(current_lap)}",
            evidence=[
                f"safety-car-status={safety_car_status}",
                f"current-lap={int(current_lap)}",
                f"player-pit-window={int(pit_window)}",
                f"average-tyre-wear={avg_wear:.1f}%",
                *choice_evidence,
            ],
            metrics={
                "current_lap": current_lap,
                "pit_window": pit_window,
                "average_tyre_wear_pct": avg_wear,
                "safety_car_status": safety_car_status,
                **choice_metrics,
            },
        )]

    tyre_stint_strategy = _strategy_tyre_stint_forecast_advice(
        tyre=tyre,
        current_lap=current_lap,
        pit_window=pit_window,
        avg_wear=avg_wear,
        compound=compound,
        tyre_choice=tyre_choice,
    )
    if tyre_stint_strategy:
        return [tyre_stint_strategy]

    weather_strategy = _weather_strategy_advice(
        telemetry_update=telemetry_update,
        current_lap=current_lap,
        pit_window=pit_window,
        avg_wear=avg_wear,
        compound=compound,
    )
    if weather_strategy:
        return weather_strategy

    opponent_strategy = _opponent_strategy_advice(
        ref_row=ref_row,
        nearby=nearby,
        current_lap=current_lap,
        pit_window=pit_window,
        avg_wear=avg_wear,
        compound=compound,
    )
    if opponent_strategy:
        return opponent_strategy

    if current_lap >= pit_window and avg_wear is not None and avg_wear >= 45:
        if traffic_risk:
            return [_item(
                item_id="strategy-pit-traffic-risk",
                category="strategy",
                priority="warning" if avg_wear >= 60 else "advisory",
                title="Pit window traffic risk",
                message=(
                    f"Pit window is open on lap {int(current_lap)}, but the gap behind is "
                    f"{_format_gap_ms(gap_behind_ms)} against an estimated pit loss of {_format_gap_ms(pit_loss_ms)}. "
                    f"Current {compound} wear averages {avg_wear:.1f}%.{choice_message}"
                ),
                voice_callout=f"Pit window open, but traffic risk on exit. Check the gap before boxing.{choice_voice}",
                cooldown_key="strategy:pit_traffic_risk",
                evidence=[
                    f"current-lap={int(current_lap)}",
                    f"player-pit-window={int(pit_window)}",
                    f"average-tyre-wear={avg_wear:.1f}%",
                    f"gap-behind={_format_gap_ms(gap_behind_ms)}",
                    f"pit-loss={_format_gap_ms(pit_loss_ms)}",
                    *choice_evidence,
                ],
                metrics={
                    "current_lap": current_lap,
                    "pit_window": pit_window,
                    "average_tyre_wear_pct": avg_wear,
                    "gap_behind_ms": gap_behind_ms,
                    "pit_loss_ms": pit_loss_ms,
                    "traffic_risk": True,
                    **choice_metrics,
                },
            )]

        if gap_behind_ms is not None and pit_loss_ms is not None:
            return [_item(
                item_id="strategy-pit-clear-air",
                category="strategy",
                priority="advisory",
                title="Pit window clear air",
                message=(
                    f"Pit window is open on lap {int(current_lap)}. Gap behind is {_format_gap_ms(gap_behind_ms)} "
                    f"against an estimated pit loss of {_format_gap_ms(pit_loss_ms)}. "
                    f"Current {compound} wear averages {avg_wear:.1f}%.{choice_message}"
                ),
                voice_callout=f"Pit window open. Gap looks clear against pit loss.{choice_voice}",
                cooldown_key="strategy:pit_clear_air",
                evidence=[
                    f"current-lap={int(current_lap)}",
                    f"player-pit-window={int(pit_window)}",
                    f"average-tyre-wear={avg_wear:.1f}%",
                    f"gap-behind={_format_gap_ms(gap_behind_ms)}",
                    f"pit-loss={_format_gap_ms(pit_loss_ms)}",
                    *choice_evidence,
                ],
                metrics={
                    "current_lap": current_lap,
                    "pit_window": pit_window,
                    "average_tyre_wear_pct": avg_wear,
                    "gap_behind_ms": gap_behind_ms,
                    "pit_loss_ms": pit_loss_ms,
                    "traffic_risk": False,
                    **choice_metrics,
                },
            )]

        return [_item(
            item_id="strategy-pit-window",
            category="strategy",
            priority="advisory",
            title="Pit window open",
            message=(
                f"Planned pit window is lap {int(pit_window)} and you are on lap {int(current_lap)}. "
                f"Current {compound} wear averages {avg_wear:.1f}%.{choice_message}"
            ),
            voice_callout=f"Pit window is open. Watch traffic before boxing.{choice_voice}",
            cooldown_key="strategy:pit_window_open",
            evidence=[
                f"current-lap={int(current_lap)}",
                f"player-pit-window={int(pit_window)}",
                f"average-tyre-wear={avg_wear:.1f}%",
                *choice_evidence,
            ],
            metrics={
                "current_lap": current_lap,
                "pit_window": pit_window,
                "average_tyre_wear_pct": avg_wear,
                **choice_metrics,
            },
        )]

    return []


def _strategy_tyre_stint_forecast_advice(
    *,
    tyre: Dict[str, Any],
    current_lap: float,
    pit_window: float,
    avg_wear: Optional[float],
    compound: Optional[str],
    tyre_choice: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if current_lap >= pit_window:
        return None

    current_wear = _dict(tyre.get("current-wear", {}))
    forecast = _tyre_stint_forecast(tyre, _tyre_wear_values(current_wear))
    if not forecast:
        return None

    projection = forecast["stint_limit"]
    threshold = _TYRE_STINT_LIMIT_WEAR_PCT
    title = "Tyre stint window"
    priority = "advisory"
    if (
        forecast["puncture_risk"]["current_wear_pct"] < _TYRE_PUNCTURE_RISK_WEAR_PCT
        and forecast["puncture_risk"]["laps_to_threshold"] <= _TYRE_PUNCTURE_WINDOW_LAPS
    ):
        projection = forecast["puncture_risk"]
        threshold = _TYRE_PUNCTURE_RISK_WEAR_PCT
        title = "Tyre puncture window"
        priority = "critical" if projection["laps_to_threshold"] <= 1.0 else "warning"
    else:
        laps_to_pit = pit_window - current_lap
        if (
            projection["current_wear_pct"] >= _TYRE_STINT_LIMIT_WEAR_PCT
            or projection["laps_to_threshold"] > _TYRE_STINT_WINDOW_LAPS
            or projection["laps_to_threshold"] > laps_to_pit + 1.0
        ):
            return None
        priority = "warning" if projection["laps_to_threshold"] <= 2.0 else "advisory"

    tyre_label = _label_tyre(projection["tyre"])
    choice_message = _tyre_choice_message_suffix(tyre_choice)
    choice_voice = _tyre_choice_voice_suffix(tyre_choice)
    choice_evidence = _tyre_choice_evidence(tyre_choice)
    choice_metrics = _tyre_choice_metrics(tyre_choice)
    evidence = [
        f"current-lap={int(current_lap)}",
        f"player-pit-window={int(pit_window)}",
        f"compound={compound}",
        f"{projection['tyre']}-wear={projection['current_wear_pct']:.1f}%",
        f"{projection['tyre']}-wear-rate={projection['wear_rate_pct_per_lap']:.2f}%/lap",
        f"projected-laps-to-{threshold:.0f}-wear={projection['laps_to_threshold']:.1f}",
        *choice_evidence,
    ]
    if avg_wear is not None:
        evidence.append(f"average-tyre-wear={avg_wear:.1f}%")

    return _item(
        item_id=f"strategy-tyre-stint-{int(threshold)}-{projection['tyre']}",
        category="strategy",
        priority=priority,
        title=title,
        message=(
            f"{tyre_label} is projected to reach {threshold:.0f}% wear in "
            f"{projection['laps_to_threshold']:.1f} laps, near the planned pit window on lap {int(pit_window)}. "
            f"Prepare the stop.{choice_message}"
        ),
        voice_callout=(
            f"{tyre_label} reaches {threshold:.0f} percent near the pit window. "
            f"Prepare to box.{choice_voice}"
        ),
        cooldown_key=f"strategy:tyre_stint:{int(threshold)}:{projection['tyre']}",
        evidence=evidence,
        metrics={
            "current_lap": current_lap,
            "pit_window": pit_window,
            "compound": compound,
            "average_tyre_wear_pct": avg_wear,
            "projected_tyre": projection["tyre"],
            "projected_threshold_pct": threshold,
            "projected_laps_to_threshold": projection["laps_to_threshold"],
            "current_wear_pct": projection["current_wear_pct"],
            "wear_rate_pct_per_lap": projection["wear_rate_pct_per_lap"],
            **choice_metrics,
        },
    )


def _tyre_choice_message_suffix(recommendation: Optional[Dict[str, Any]]) -> str:
    if not recommendation:
        return ""
    return f" Tyre call: {recommendation['compound']}."


def _tyre_choice_voice_suffix(recommendation: Optional[Dict[str, Any]]) -> str:
    if not recommendation:
        return ""
    return f" Target {recommendation['compound']}."


def _tyre_choice_evidence(recommendation: Optional[Dict[str, Any]]) -> List[str]:
    if not recommendation:
        return []
    evidence = [
        f"recommended-compound={recommendation['compound']}",
        f"recommendation-source={recommendation['source']}",
        f"recommendation-reason={recommendation['reason']}",
    ]
    if recommendation.get("set_index") is not None:
        evidence.append(f"recommended-tyre-set-index={recommendation['set_index']}")
    return evidence


def _tyre_choice_metrics(recommendation: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not recommendation:
        return {}
    metrics = {
        "recommended_next_compound": recommendation["compound"],
        "recommended_next_tyre_source": recommendation["source"],
        "recommended_next_tyre_reason": recommendation["reason"],
    }
    for key in (
        "actual_compound",
        "set_index",
        "usable_life_laps",
        "life_span_laps",
        "wear_pct",
        "lap_delta_ms",
        "remaining_laps_after_stop",
        "longest_stint_laps",
        "lowest_wear_per_lap_pct",
    ):
        if key in recommendation:
            metrics[f"recommended_next_tyre_{key}"] = recommendation[key]
    return metrics


def _tyre_compound_pace_advice(
    telemetry_update: Dict[str, Any],
    ref_row: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    analysis = _tyre_compound_analysis(telemetry_update, ref_row)
    fastest = analysis.get("fastest_live_compound")
    if not fastest or fastest.get("compound_count", 0) < 2:
        return None

    recommendation = analysis.get("recommendation")
    gap_to_next = _num(fastest.get("gap_to_next_compound_ms"))
    gap_text = (
        f" The next best compound is {_format_gap_ms(gap_to_next)} back."
        if gap_to_next is not None and gap_to_next > 0
        else ""
    )
    choice_text = f" Tyre call is {recommendation['compound']}." if recommendation else ""
    priority = "advisory" if gap_to_next is not None and gap_to_next >= 300 else "info"
    driver_name = fastest.get("driver_name") or "a car on track"
    lap_time = _format_lap_time_ms(fastest["lap_time_ms"])

    return _item(
        item_id=f"tyres-fastest-compound-{_compound_id(fastest['compound'])}",
        category="tyres",
        priority=priority,
        title="Fastest live compound",
        message=(
            f"{fastest['compound']} is the quickest live compound on recent valid laps: "
            f"{driver_name} did {lap_time}.{gap_text}{choice_text}"
        ),
        voice_callout=(
            f"{fastest['compound']} looks quickest right now. "
            f"{driver_name} did {lap_time}."
            f"{_tyre_choice_voice_suffix(recommendation)}"
        ),
        cooldown_key=f"tyres:fastest_compound:{_compound_id(fastest['compound'])}",
        evidence=[
            f"fastest-live-compound={fastest['compound']}",
            f"fastest-live-driver={driver_name}",
            f"fastest-live-lap={lap_time}",
            f"compound-count={fastest.get('compound_count')}",
            *(_tyre_choice_evidence(recommendation)[:4]),
        ],
        metrics={
            "fastest_live_compound": fastest["compound"],
            "fastest_live_lap_ms": fastest["lap_time_ms"],
            "fastest_live_driver": fastest.get("driver_name"),
            "gap_to_next_compound_ms": gap_to_next,
            "compound_count": fastest.get("compound_count"),
            **_tyre_choice_metrics(recommendation),
        },
    )


def _tyre_compound_analysis(
    telemetry_update: Dict[str, Any],
    ref_row: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    telemetry_update = _dict(telemetry_update)
    live_ranking = _live_compound_ranking(_list_of_dicts(telemetry_update.get("table-entries", [])))
    fastest_live = live_ranking[0] if live_ranking else None
    records = _tyre_stats_records(_dict(telemetry_update.get("records", {})).get("tyre-stats"))
    tyre_sets = _available_tyre_set_options(telemetry_update)
    recommendation = _next_tyre_recommendation(
        telemetry_update=telemetry_update,
        ref_row=ref_row,
        fastest_live=fastest_live,
        records=records,
        tyre_sets=tyre_sets,
    )
    return {
        "live_compound_ranking": live_ranking,
        "fastest_live_compound": fastest_live,
        "records": records,
        "available_tyre_sets": tyre_sets,
        "recommendation": recommendation,
    }


def _live_compound_ranking(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    samples_by_compound: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        tyre = _dict(row.get("tyre-info", {}))
        compound = _normalise_compound_name(_safe_text(tyre.get("visual-tyre-compound")))
        if not compound:
            continue
        last_lap = _dict(_dict(row.get("lap-info", {})).get("last-lap", {}))
        if last_lap.get("is-valid") is False:
            continue
        lap_ms = _num(last_lap.get("lap-time-ms"))
        if lap_ms is None or lap_ms <= 0:
            continue
        driver = _dict(row.get("driver-info", {}))
        current_wear = _dict(tyre.get("current-wear", {}))
        samples_by_compound.setdefault(compound, []).append({
            "compound": compound,
            "lap_time_ms": lap_ms,
            "driver_name": _safe_text(driver.get("name")),
            "driver_index": _int_or_none(driver.get("index")),
            "position": _int_or_none(driver.get("position")),
            "tyre_age_laps": _int_or_none(tyre.get("tyre-age")),
            "average_wear_pct": _num(current_wear.get("average")),
        })

    ranking: List[Dict[str, Any]] = []
    for compound, samples in samples_by_compound.items():
        best = min(samples, key=lambda sample: sample["lap_time_ms"])
        ranking.append({**best, "sample_count": len(samples)})
    ranking.sort(key=lambda sample: sample["lap_time_ms"])
    if ranking:
        ranking[0]["compound_count"] = len(ranking)
        if len(ranking) > 1:
            ranking[0]["gap_to_next_compound_ms"] = ranking[1]["lap_time_ms"] - ranking[0]["lap_time_ms"]
    return ranking


def _available_tyre_set_options(telemetry_update: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = _dict(telemetry_update.get("player-tyre-sets")) or _dict(telemetry_update.get("tyre-sets"))
    tyre_sets = _list_of_dicts(payload.get("tyre-set-data", []))
    options: List[Dict[str, Any]] = []
    for index, tyre_set in enumerate(tyre_sets):
        if tyre_set.get("available") is not True or tyre_set.get("fitted") is True:
            continue
        compound = _normalise_compound_name(_safe_text(tyre_set.get("visual-tyre-compound")))
        if not compound:
            continue
        wear = _num(tyre_set.get("wear"), 0.0)
        if wear is not None and wear >= 90:
            continue
        options.append({
            "compound": compound,
            "actual_compound": _safe_text(tyre_set.get("actual-tyre-compound")),
            "set_index": index,
            "wear_pct": wear,
            "usable_life_laps": _num(tyre_set.get("usable-life")),
            "life_span_laps": _num(tyre_set.get("life-span")),
            "lap_delta_ms": _num(tyre_set.get("lap-delta-time")),
            "recommended_session": _safe_text(tyre_set.get("recommended-session")),
        })
    return options


def _tyre_stats_records(value: Any) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = {}
    for key, raw_record in _dict(value).items():
        record = _dict(raw_record)
        parts = [part.strip() for part in str(key).split(" - ") if part.strip()]
        actual = parts[0] if len(parts) >= 2 else None
        compound = _normalise_compound_name(parts[-1] if parts else None)
        if not compound:
            continue
        longest = _dict(record.get("longest-tyre-stint", {}))
        lowest_wear = _dict(record.get("lowest-tyre-wear-per-lap", {}))
        highest_wear = _dict(record.get("highest-tyre-wear", {}))
        candidate = {
            "compound": compound,
            "actual_compound": actual,
            "longest_stint_laps": _num(longest.get("value")),
            "longest_stint_driver": _safe_text(longest.get("driver-name")),
            "lowest_wear_per_lap_pct": _num(lowest_wear.get("value")),
            "lowest_wear_driver": _safe_text(lowest_wear.get("driver-name")),
            "highest_wear_pct": _num(highest_wear.get("value")),
        }
        existing = records.get(compound)
        if not existing or _record_is_better_for_strategy(candidate, existing):
            records[compound] = candidate
    return records


def _record_is_better_for_strategy(candidate: Dict[str, Any], existing: Dict[str, Any]) -> bool:
    candidate_wear = _num(candidate.get("lowest_wear_per_lap_pct"), 999.0)
    existing_wear = _num(existing.get("lowest_wear_per_lap_pct"), 999.0)
    if candidate_wear != existing_wear:
        return candidate_wear < existing_wear
    return _num(candidate.get("longest_stint_laps"), 0.0) > _num(existing.get("longest_stint_laps"), 0.0)


def _next_tyre_recommendation(
    *,
    telemetry_update: Dict[str, Any],
    ref_row: Optional[Dict[str, Any]],
    fastest_live: Optional[Dict[str, Any]],
    records: Dict[str, Dict[str, Any]],
    tyre_sets: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    remaining_laps = _remaining_laps_after_stop(telemetry_update)
    current_compound = _normalise_compound_name(
        _safe_text(_dict(_dict(ref_row or {}).get("tyre-info", {})).get("visual-tyre-compound"))
    )
    if tyre_sets:
        scored = [
            _score_tyre_set_option(option, telemetry_update, remaining_laps, fastest_live, records)
            for option in tyre_sets
        ]
        scored.sort(key=lambda item: item["score"])
        best = scored[0]
        record = records.get(best["compound"], {})
        reason = _tyre_set_reason(best, remaining_laps, record)
        recommendation = {
            **best,
            "source": "tyre_sets",
            "reason": reason,
            "remaining_laps_after_stop": remaining_laps,
        }
        if record:
            recommendation["longest_stint_laps"] = record.get("longest_stint_laps")
            recommendation["lowest_wear_per_lap_pct"] = record.get("lowest_wear_per_lap_pct")
        return recommendation

    record_recommendation = _recommend_from_tyre_records(records, remaining_laps, current_compound)
    if record_recommendation:
        return record_recommendation

    if fastest_live and fastest_live.get("compound_count", 0) >= 2:
        return {
            "compound": fastest_live["compound"],
            "source": "live_pace",
            "reason": "fastest live compound",
            "remaining_laps_after_stop": remaining_laps,
        }
    return None


def _score_tyre_set_option(
    option: Dict[str, Any],
    telemetry_update: Dict[str, Any],
    remaining_laps: Optional[float],
    fastest_live: Optional[Dict[str, Any]],
    records: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    score = _num(option.get("lap_delta_ms"), 0.0) or 0.0
    score += (_num(option.get("wear_pct"), 0.0) or 0.0) * 30.0
    score += _compound_weather_penalty(option["compound"], telemetry_update)

    usable_life = _num(option.get("usable_life_laps")) or _num(option.get("life_span_laps"))
    if remaining_laps is not None:
        if usable_life is None or usable_life <= 0:
            score += 500.0
        else:
            life_margin = usable_life - remaining_laps
            if life_margin < -1.0:
                score += 5000.0 + abs(life_margin) * 1000.0
            else:
                score -= min(max(life_margin, 0.0), 5.0) * 20.0

    if fastest_live and fastest_live.get("compound") == option["compound"]:
        score -= 250.0

    record = records.get(option["compound"])
    if record:
        wear_per_lap = _num(record.get("lowest_wear_per_lap_pct"))
        if wear_per_lap is not None:
            score += wear_per_lap * 40.0
        longest = _num(record.get("longest_stint_laps"))
        if remaining_laps is not None and longest is not None and longest < remaining_laps - 1.0:
            score += 1500.0 + (remaining_laps - longest) * 100.0

    return {**option, "score": score}


def _recommend_from_tyre_records(
    records: Dict[str, Dict[str, Any]],
    remaining_laps: Optional[float],
    current_compound: Optional[str],
) -> Optional[Dict[str, Any]]:
    if not records:
        return None
    candidates = []
    for record in records.values():
        longest = _num(record.get("longest_stint_laps"))
        wear = _num(record.get("lowest_wear_per_lap_pct"), 999.0)
        score = wear * 100.0
        if remaining_laps is not None and longest is not None:
            if longest < remaining_laps - 1.0:
                score += 5000.0 + (remaining_laps - longest) * 100.0
            else:
                score -= min(longest - remaining_laps, 5.0) * 20.0
        if current_compound and record["compound"] == current_compound:
            score += 50.0
        candidates.append((score, record))
    candidates.sort(key=lambda item: item[0])
    best = candidates[0][1]
    reason = "best stint record"
    if best.get("longest_stint_laps") is not None:
        reason = f"stint data supports {best['longest_stint_laps']:.0f} laps"
    if best.get("lowest_wear_per_lap_pct") is not None:
        reason += f", {best['lowest_wear_per_lap_pct']:.2f}% wear per lap"
    return {
        "compound": best["compound"],
        "actual_compound": best.get("actual_compound"),
        "source": "tyre_stats",
        "reason": reason,
        "remaining_laps_after_stop": remaining_laps,
        "longest_stint_laps": best.get("longest_stint_laps"),
        "lowest_wear_per_lap_pct": best.get("lowest_wear_per_lap_pct"),
    }


def _tyre_set_reason(
    option: Dict[str, Any],
    remaining_laps: Optional[float],
    record: Dict[str, Any],
) -> str:
    reason_parts = ["available set"]
    usable_life = _num(option.get("usable_life_laps")) or _num(option.get("life_span_laps"))
    if usable_life is not None:
        if remaining_laps is not None and usable_life >= remaining_laps - 1.0:
            reason_parts.append(f"covers {remaining_laps:.0f} laps")
        else:
            reason_parts.append(f"{usable_life:.0f} lap life")
    lap_delta = _num(option.get("lap_delta_ms"))
    if lap_delta is not None and lap_delta != 0:
        direction = "faster" if lap_delta < 0 else "slower"
        reason_parts.append(f"{abs(lap_delta) / 1000.0:.1f}s {direction} than fitted")
    elif lap_delta == 0:
        reason_parts.append("same delta as fitted")
    if record.get("lowest_wear_per_lap_pct") is not None:
        reason_parts.append(f"{record['lowest_wear_per_lap_pct']:.2f}% wear per lap in stint data")
    return ", ".join(reason_parts[:3])


def _remaining_laps_after_stop(telemetry_update: Dict[str, Any]) -> Optional[float]:
    current_lap = _num(telemetry_update.get("current-lap"))
    total_laps = _num(telemetry_update.get("total-laps"))
    if current_lap is None or total_laps is None or total_laps <= 0:
        return None
    return max(1.0, total_laps - current_lap)


def _compound_weather_penalty(compound: str, telemetry_update: Dict[str, Any]) -> float:
    samples = _weather_samples(telemetry_update)
    current_weather_sample = _current_weather_sample(samples)
    current_weather = _safe_text(_dict(current_weather_sample or {}).get("weather"))
    if current_weather and _is_wet_weather(current_weather):
        return 0.0 if _is_wet_tyre_compound(compound) else 6000.0

    transition = _next_weather_transition(samples)
    if transition and transition["to_wet"] and transition["time_offset_min"] <= 6:
        return 0.0 if _is_wet_tyre_compound(compound) else 1500.0

    return 6000.0 if _is_wet_tyre_compound(compound) else 0.0


def _normalise_compound_name(value: Optional[str]) -> Optional[str]:
    compound = _safe_text(value, max_len=32)
    if not compound:
        return None
    normalised = compound.strip()
    if normalised.lower() in {"unknown", "none", "---"}:
        return None
    return normalised


def _compound_id(compound: str) -> str:
    return compound.lower().replace(" ", "-").replace("_", "-")


def _opponent_strategy_advice(
    *,
    ref_row: Dict[str, Any],
    nearby: Dict[str, Any],
    current_lap: float,
    pit_window: float,
    avg_wear: Optional[float],
    compound: Optional[str],
) -> List[Dict[str, Any]]:
    if current_lap < pit_window - 1 or avg_wear is None:
        return []

    player_stint = _strategy_stint_from_row(ref_row)
    player_last_lap_ms = _last_lap_ms(ref_row)
    behind = nearby.get("car_behind")
    if behind:
        behind_advice = _undercut_threat_advice(
            behind=behind,
            player_stint=player_stint,
            player_last_lap_ms=player_last_lap_ms,
            current_lap=current_lap,
            pit_window=pit_window,
            avg_wear=avg_wear,
            compound=compound,
        )
        if behind_advice:
            return [behind_advice]

    ahead = nearby.get("car_ahead")
    if ahead:
        ahead_advice = _undercut_opportunity_advice(
            ahead=ahead,
            player_stint=player_stint,
            player_last_lap_ms=player_last_lap_ms,
            current_lap=current_lap,
            pit_window=pit_window,
            avg_wear=avg_wear,
            compound=compound,
        )
        if ahead_advice:
            return [ahead_advice]

    return []


def _undercut_threat_advice(
    *,
    behind: Dict[str, Any],
    player_stint: Dict[str, Any],
    player_last_lap_ms: Optional[float],
    current_lap: float,
    pit_window: float,
    avg_wear: float,
    compound: Optional[str],
) -> Optional[Dict[str, Any]]:
    gap_behind_ms = _num(behind.get("gap_ms"))
    if gap_behind_ms is None or gap_behind_ms <= 0 or gap_behind_ms > 8000:
        return None

    behind_lap_ms = _num(behind.get("last_lap_ms"))
    behind_lap_delta_ms = (
        player_last_lap_ms - behind_lap_ms
        if player_last_lap_ms is not None and behind_lap_ms is not None
        else None
    )
    behind_stint = _strategy_stint_from_nearby(behind)
    tyre_wear_delta = _stint_wear_delta(player_stint, behind_stint)
    tyre_age_delta = _stint_age_delta(player_stint, behind_stint)
    player_stops = _int_or_none(player_stint.get("num_pitstops"))
    behind_stops = _int_or_none(behind_stint.get("num_pitstops"))
    behind_already_stopped = (
        player_stops is not None and behind_stops is not None and behind_stops > player_stops
    )
    behind_same_stops = (
        player_stops is not None and behind_stops is not None and behind_stops == player_stops
    )
    behind_faster = behind_lap_delta_ms is not None and behind_lap_delta_ms >= 400
    behind_has_better_tyres = (
        (tyre_wear_delta is not None and tyre_wear_delta >= 8)
        or (tyre_age_delta is not None and tyre_age_delta >= 4)
    )

    if behind_already_stopped and (behind_faster or behind_has_better_tyres):
        return _item(
            item_id="strategy-undercut-threat",
            category="strategy",
            priority="warning",
            title="Undercut threat",
            message=(
                f"{behind.get('name') or 'Car behind'} has already stopped and is {_format_gap_ms(gap_behind_ms)} "
                "behind. Cover soon if your tyres keep fading."
            ),
            voice_callout="Undercut threat behind. Cover soon if the tyres keep fading.",
            cooldown_key="strategy:undercut_threat",
            evidence=_opponent_strategy_evidence(
                current_lap=current_lap,
                pit_window=pit_window,
                compound=compound,
                avg_wear=avg_wear,
                opponent=behind,
                lap_delta_ms=behind_lap_delta_ms,
                tyre_wear_delta=tyre_wear_delta,
                tyre_age_delta=tyre_age_delta,
            ),
            metrics={
                "current_lap": current_lap,
                "pit_window": pit_window,
                "gap_behind_ms": gap_behind_ms,
                "behind_lap_delta_ms": behind_lap_delta_ms,
                "tyre_wear_delta_pct": tyre_wear_delta,
                "tyre_age_delta_laps": tyre_age_delta,
                "player_pit_stops": player_stops,
                "opponent_pit_stops": behind_stops,
            },
        )

    if behind_same_stops and gap_behind_ms <= 3500 and avg_wear >= 45 and (behind_faster or behind_has_better_tyres):
        return _item(
            item_id="strategy-cover-undercut",
            category="strategy",
            priority="warning" if avg_wear >= 55 or gap_behind_ms <= 2000 else "advisory",
            title="Cover undercut",
            message=(
                f"{behind.get('name') or 'Car behind'} is close at {_format_gap_ms(gap_behind_ms)} and has "
                "undercut pressure. Cover the stop if pit exit traffic is acceptable."
            ),
            voice_callout="Undercut pressure behind. Cover if the pit exit is clean.",
            cooldown_key="strategy:cover_undercut",
            evidence=_opponent_strategy_evidence(
                current_lap=current_lap,
                pit_window=pit_window,
                compound=compound,
                avg_wear=avg_wear,
                opponent=behind,
                lap_delta_ms=behind_lap_delta_ms,
                tyre_wear_delta=tyre_wear_delta,
                tyre_age_delta=tyre_age_delta,
            ),
            metrics={
                "current_lap": current_lap,
                "pit_window": pit_window,
                "gap_behind_ms": gap_behind_ms,
                "behind_lap_delta_ms": behind_lap_delta_ms,
                "tyre_wear_delta_pct": tyre_wear_delta,
                "tyre_age_delta_laps": tyre_age_delta,
                "player_pit_stops": player_stops,
                "opponent_pit_stops": behind_stops,
            },
        )

    return None


def _undercut_opportunity_advice(
    *,
    ahead: Dict[str, Any],
    player_stint: Dict[str, Any],
    player_last_lap_ms: Optional[float],
    current_lap: float,
    pit_window: float,
    avg_wear: float,
    compound: Optional[str],
) -> Optional[Dict[str, Any]]:
    if current_lap < pit_window:
        return None

    gap_ahead_ms = _num(ahead.get("gap_ms"))
    if gap_ahead_ms is None or gap_ahead_ms <= 0 or gap_ahead_ms > 5000:
        return None

    ahead_lap_ms = _num(ahead.get("last_lap_ms"))
    player_lap_delta_ms = (
        ahead_lap_ms - player_last_lap_ms
        if player_last_lap_ms is not None and ahead_lap_ms is not None
        else None
    )
    ahead_stint = _strategy_stint_from_nearby(ahead)
    wear_advantage = _stint_wear_delta(ahead_stint, player_stint)
    age_advantage = _stint_age_delta(ahead_stint, player_stint)
    player_stops = _int_or_none(player_stint.get("num_pitstops"))
    ahead_stops = _int_or_none(ahead_stint.get("num_pitstops"))
    same_stops = player_stops is not None and ahead_stops is not None and player_stops == ahead_stops
    player_faster = player_lap_delta_ms is not None and player_lap_delta_ms >= 400
    player_has_better_tyres = (
        (wear_advantage is not None and wear_advantage >= 8)
        or (age_advantage is not None and age_advantage >= 4)
    )

    if not same_stops or avg_wear >= 65 or not (player_faster or player_has_better_tyres):
        return None

    return _item(
        item_id="strategy-undercut-opportunity",
        category="strategy",
        priority="advisory",
        title="Undercut opportunity",
        message=(
            f"{ahead.get('name') or 'Car ahead'} is within {_format_gap_ms(gap_ahead_ms)} and looks vulnerable. "
            "An undercut is worth considering if the pit exit is clear."
        ),
        voice_callout="Undercut opportunity ahead. Consider it if pit exit is clear.",
        cooldown_key="strategy:undercut_opportunity",
        evidence=_opponent_strategy_evidence(
            current_lap=current_lap,
            pit_window=pit_window,
            compound=compound,
            avg_wear=avg_wear,
            opponent=ahead,
            lap_delta_ms=player_lap_delta_ms,
            tyre_wear_delta=wear_advantage,
            tyre_age_delta=age_advantage,
        ),
        metrics={
            "current_lap": current_lap,
            "pit_window": pit_window,
            "gap_ahead_ms": gap_ahead_ms,
            "player_lap_delta_to_ahead_ms": player_lap_delta_ms,
            "tyre_wear_advantage_pct": wear_advantage,
            "tyre_age_advantage_laps": age_advantage,
            "player_pit_stops": player_stops,
            "opponent_pit_stops": ahead_stops,
        },
    )


def _strategy_stint_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    tyre = _dict(row.get("tyre-info", {}))
    wear = _dict(tyre.get("current-wear", {}))
    return {
        "compound": _safe_text(tyre.get("visual-tyre-compound")),
        "tyre_age_laps": _int_or_none(tyre.get("tyre-age")),
        "average_tyre_wear_pct": _num(wear.get("average")),
        "num_pitstops": _int_or_none(tyre.get("num-pitstops")),
    }


def _strategy_stint_from_nearby(nearby: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "compound": _safe_text(nearby.get("compound")),
        "tyre_age_laps": _int_or_none(nearby.get("tyre_age_laps")),
        "average_tyre_wear_pct": _num(nearby.get("average_tyre_wear_pct")),
        "num_pitstops": _int_or_none(nearby.get("num_pitstops")),
    }


def _stint_wear_delta(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Optional[float]:
    primary_wear = _num(primary.get("average_tyre_wear_pct"))
    secondary_wear = _num(secondary.get("average_tyre_wear_pct"))
    if primary_wear is None or secondary_wear is None:
        return None
    return primary_wear - secondary_wear


def _stint_age_delta(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Optional[int]:
    primary_age = _int_or_none(primary.get("tyre_age_laps"))
    secondary_age = _int_or_none(secondary.get("tyre_age_laps"))
    if primary_age is None or secondary_age is None:
        return None
    return primary_age - secondary_age


def _nearby_strategy_facts(label: str, nearby: Dict[str, Any]) -> List[str]:
    facts: List[str] = []
    name = nearby.get("name") or "unknown"
    compound = _safe_text(nearby.get("compound"))
    tyre_age = _int_or_none(nearby.get("tyre_age_laps"))
    avg_wear = _num(nearby.get("average_tyre_wear_pct"))
    pit_stops = _int_or_none(nearby.get("num_pitstops"))
    if compound or tyre_age is not None or avg_wear is not None or pit_stops is not None:
        facts.append(
            f"{label} stint: {name}, "
            f"{compound or 'unknown'}"
            f"{f', age {tyre_age} laps' if tyre_age is not None else ''}"
            f"{f', wear {avg_wear:.1f}%' if avg_wear is not None else ''}"
            f"{f', stops {pit_stops}' if pit_stops is not None else ''}"
        )
    return facts


def _opponent_strategy_evidence(
    *,
    current_lap: float,
    pit_window: float,
    compound: Optional[str],
    avg_wear: float,
    opponent: Dict[str, Any],
    lap_delta_ms: Optional[float],
    tyre_wear_delta: Optional[float],
    tyre_age_delta: Optional[int],
) -> List[str]:
    evidence = [
        f"current-lap={int(current_lap)}",
        f"player-pit-window={int(pit_window)}",
        f"compound={compound}",
        f"average-tyre-wear={avg_wear:.1f}%",
        f"opponent={opponent.get('name') or 'unknown'}",
        f"opponent-gap={opponent.get('gap') or 'unknown'}",
    ]
    opponent_pit_stops = _int_or_none(opponent.get("num_pitstops"))
    if opponent_pit_stops is not None:
        evidence.append(f"opponent-pit-stops={opponent_pit_stops}")
    if lap_delta_ms is not None:
        evidence.append(f"lap-delta={_format_gap_ms(lap_delta_ms)}")
    if tyre_wear_delta is not None:
        evidence.append(f"tyre-wear-delta={tyre_wear_delta:.1f}%")
    if tyre_age_delta is not None:
        evidence.append(f"tyre-age-delta={tyre_age_delta}")
    return evidence


def _weather_strategy_advice(
    *,
    telemetry_update: Dict[str, Any],
    current_lap: float,
    pit_window: float,
    avg_wear: Optional[float],
    compound: Optional[str],
) -> List[Dict[str, Any]]:
    if current_lap < pit_window - 1:
        return []
    if avg_wear is None or avg_wear >= 70:
        return []

    samples = _weather_samples(telemetry_update)
    if not samples:
        return []

    transition = _next_weather_transition(samples)
    if (
            transition
            and transition["to_wet"]
            and not transition["from_wet"]
            and transition["time_offset_min"] <= 12
            and _is_dry_tyre_compound(compound)):
        minutes = int(transition["time_offset_min"])
        rain_pct = _num(transition.get("rain_pct"))
        return [_item(
            item_id="strategy-hold-for-rain",
            category="strategy",
            priority="warning",
            title="Hold for rain",
            message=(
                f"Pit window is open, but forecast shifts to {transition['to_weather']} in {minutes} minutes. "
                f"Current {compound} wear averages {avg_wear:.1f}%, so avoid committing to another dry set "
                "unless the tyres fall away."
            ),
            voice_callout=f"Pit window open, but rain is close. Avoid another dry set unless tyres drop off.",
            cooldown_key="strategy:hold_for_rain",
            evidence=[
                f"current-lap={int(current_lap)}",
                f"player-pit-window={int(pit_window)}",
                f"compound={compound}",
                f"average-tyre-wear={avg_wear:.1f}%",
                f"forecast-weather={transition['to_weather']}",
                f"time-offset-min={minutes}",
                f"rain-probability={rain_pct:.0f}%" if rain_pct is not None else "rain-probability=unavailable",
            ],
            metrics={
                "current_lap": current_lap,
                "pit_window": pit_window,
                "average_tyre_wear_pct": avg_wear,
                "compound": compound,
                "weather_transition_minutes": transition["time_offset_min"],
                "weather_transition_to": transition["to_weather"],
                "rain_probability_pct": rain_pct,
            },
        )]

    rain_risk = _highest_rain_risk(samples, within_minutes=12)
    current_weather = _weather_name(_current_weather_sample(samples))
    if (
            rain_risk
            and rain_risk["rain_pct"] >= 70
            and not _is_wet_weather(current_weather)
            and _is_dry_tyre_compound(compound)):
        minutes = int(rain_risk["time_offset_min"])
        return [_item(
            item_id="strategy-hold-for-rain-risk",
            category="strategy",
            priority="advisory",
            title="Rain risk near pit window",
            message=(
                f"Rain probability reaches {rain_risk['rain_pct']:.0f}% in {minutes} minutes while the pit "
                f"window is open. Keep this dry stint flexible before committing to another {compound} set."
            ),
            voice_callout=f"Rain risk high near the pit window. Keep the dry stint flexible.",
            cooldown_key="strategy:hold_for_rain_risk",
            evidence=[
                f"current-lap={int(current_lap)}",
                f"player-pit-window={int(pit_window)}",
                f"compound={compound}",
                f"average-tyre-wear={avg_wear:.1f}%",
                f"rain-probability={rain_risk['rain_pct']:.0f}%",
                f"time-offset-min={minutes}",
            ],
            metrics={
                "current_lap": current_lap,
                "pit_window": pit_window,
                "average_tyre_wear_pct": avg_wear,
                "compound": compound,
                "rain_risk_pct": rain_risk["rain_pct"],
                "rain_risk_minutes": rain_risk["time_offset_min"],
            },
        )]

    if (
            transition
            and transition["from_wet"]
            and not transition["to_wet"]
            and transition["time_offset_min"] <= 15
            and _is_wet_tyre_compound(compound)):
        minutes = int(transition["time_offset_min"])
        return [_item(
            item_id="strategy-drying-crossover",
            category="strategy",
            priority="advisory",
            title="Drying crossover",
            message=(
                f"Pit window is open on {compound}, but forecast moves to {transition['to_weather']} in "
                f"{minutes} minutes. Avoid another wet tyre call unless wear or pace forces it."
            ),
            voice_callout=f"Drying window near the pit stop. Avoid another wet set unless pace drops.",
            cooldown_key="strategy:drying_crossover",
            evidence=[
                f"current-lap={int(current_lap)}",
                f"player-pit-window={int(pit_window)}",
                f"compound={compound}",
                f"average-tyre-wear={avg_wear:.1f}%",
                f"forecast-weather={transition['to_weather']}",
                f"time-offset-min={minutes}",
            ],
            metrics={
                "current_lap": current_lap,
                "pit_window": pit_window,
                "average_tyre_wear_pct": avg_wear,
                "compound": compound,
                "weather_transition_minutes": transition["time_offset_min"],
                "weather_transition_to": transition["to_weather"],
            },
        )]

    return []


def _tyre_wear_values(current: Dict[str, Any]) -> Dict[str, float]:
    wear_values = {
        "front-left": _num(current.get("front-left-wear")),
        "front-right": _num(current.get("front-right-wear")),
        "rear-left": _num(current.get("rear-left-wear")),
        "rear-right": _num(current.get("rear-right-wear")),
    }
    return {name: value for name, value in wear_values.items() if value is not None}


def _damage_parts(ref_row: Dict[str, Any]) -> Dict[str, float]:
    damage = _dict(ref_row.get("damage-info", {}))
    parts = {
        "front-left wing": _num(damage.get("fl-wing-damage")),
        "front-right wing": _num(damage.get("fr-wing-damage")),
        "rear wing": _num(damage.get("rear-wing-damage")),
        "floor": _num(damage.get("floor-damage")),
        "diffuser": _num(damage.get("diffuser-damage")),
        "sidepod": _num(damage.get("sidepod-damage")),
    }
    return {name: value for name, value in parts.items() if value is not None}


def _damage_faults(ref_row: Dict[str, Any]) -> List[str]:
    damage = _dict(ref_row.get("damage-info", {}))
    faults: List[str] = []
    for field, label in (
        ("engine-blown", "engine blown"),
        ("engine-seized", "engine seized"),
        ("ers-fault", "ERS fault"),
        ("drs-fault", "DRS fault"),
    ):
        if damage.get(field) is True:
            faults.append(label)
    return faults


def _powertrain_damage_parts(ref_row: Dict[str, Any]) -> Dict[str, float]:
    damage = _dict(ref_row.get("damage-info", {}))
    parts = {
        "gear-box": _num(damage.get("gear-box-damage")),
        "engine": _num(damage.get("engine-damage")),
        "engine-mguh": _num(damage.get("engine-mguh-wear")),
        "engine-es": _num(damage.get("engine-es-wear")),
        "engine-ce": _num(damage.get("engine-ce-wear")),
        "engine-ice": _num(damage.get("engine-ice-wear")),
        "engine-mguk": _num(damage.get("engine-mguk-wear")),
        "engine-tc": _num(damage.get("engine-tc-wear")),
    }
    return {name: value for name, value in parts.items() if value is not None}


def _weather_samples(telemetry_update: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_samples = _list_of_dicts(telemetry_update.get("weather-forecast-samples", []))
    session_type = _safe_text(telemetry_update.get("event-type")) or _safe_text(telemetry_update.get("session-type"))
    session_samples = [
        sample for sample in raw_samples
        if _weather_sample_matches_session(sample, session_type)
    ]
    samples = session_samples or raw_samples
    samples = [
        sample for sample in samples
        if _num(sample.get("time-offset")) is not None
    ]
    return sorted(samples, key=lambda sample: _num(sample.get("time-offset"), 9999.0))


def _weather_sample_matches_session(sample: Dict[str, Any], session_type: Optional[str]) -> bool:
    if not session_type:
        return True
    sample_session = _safe_text(sample.get("session-type"))
    if not sample_session:
        return True
    return _normalise_weather_session(sample_session) == _normalise_weather_session(session_type)


def _normalise_weather_session(value: str) -> str:
    return value.lower().replace("_", " ").replace("-", " ").strip()


def _current_weather_sample(samples: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not samples:
        return None
    zero_offset = next(
        (sample for sample in samples if _num(sample.get("time-offset")) == 0),
        None,
    )
    if zero_offset:
        return zero_offset
    future_samples = [
        sample for sample in samples
        if (_num(sample.get("time-offset")) is not None and _num(sample.get("time-offset")) >= 0)
    ]
    return future_samples[0] if future_samples else samples[0]


def _weather_name(sample: Optional[Dict[str, Any]]) -> Optional[str]:
    if not sample:
        return None
    return _safe_text(sample.get("weather"))


def _rain_percentage(sample: Dict[str, Any]) -> Optional[float]:
    value = _num(sample.get("rain-percentage"))
    if value is not None:
        return value
    return _num(sample.get("rain-probability"))


def _next_weather_transition(samples: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    current = _current_weather_sample(samples)
    if not current:
        return None

    current_offset = _num(current.get("time-offset"), 0.0) or 0.0
    current_weather = _weather_name(current)
    current_wet = _is_wet_weather(current_weather)
    if current_weather is None:
        return None

    for sample in samples:
        offset = _num(sample.get("time-offset"))
        if offset is None or offset <= current_offset:
            continue
        forecast_weather = _weather_name(sample)
        if forecast_weather is None:
            continue
        forecast_wet = _is_wet_weather(forecast_weather)
        if forecast_wet == current_wet:
            continue
        return {
            "time_offset_min": offset,
            "from_weather": current_weather,
            "to_weather": forecast_weather,
            "from_wet": current_wet,
            "to_wet": forecast_wet,
            "rain_pct": _rain_percentage(sample),
        }
    return None


def _highest_rain_risk(samples: List[Dict[str, Any]], *, within_minutes: int) -> Optional[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for sample in samples:
        offset = _num(sample.get("time-offset"))
        rain_pct = _rain_percentage(sample)
        if offset is None or rain_pct is None or offset < 0 or offset > within_minutes:
            continue
        candidates.append({
            "time_offset_min": offset,
            "rain_pct": rain_pct,
            "weather": _weather_name(sample),
        })
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item["rain_pct"], -item["time_offset_min"]))


def _track_temperature_shift(
    samples: List[Dict[str, Any]],
    *,
    within_minutes: int,
) -> Optional[Dict[str, Any]]:
    current = _current_weather_sample(samples)
    if not current:
        return None

    current_offset = _num(current.get("time-offset"), 0.0) or 0.0
    current_temp = _num(current.get("track-temperature"))
    if current_temp is None:
        return None

    shifts: List[Dict[str, Any]] = []
    for sample in samples:
        offset = _num(sample.get("time-offset"))
        future_temp = _num(sample.get("track-temperature"))
        if offset is None or future_temp is None or offset <= current_offset or offset > within_minutes:
            continue
        shifts.append({
            "time_offset_min": offset,
            "delta_c": future_temp - current_temp,
            "current_temp_c": current_temp,
            "future_temp_c": future_temp,
        })
    if not shifts:
        return None
    return max(shifts, key=lambda item: abs(item["delta_c"]))


def _is_wet_weather(weather: Optional[str]) -> bool:
    if not weather:
        return False
    normalised = weather.strip().lower().replace("_", " ").replace("-", " ")
    return "rain" in normalised or "storm" in normalised or "thunder" in normalised


def _is_wet_tyre_compound(compound: Optional[str]) -> bool:
    if not compound:
        return False
    normalised = compound.strip().lower().replace("_", " ").replace("-", " ")
    return "inter" in normalised or "wet" in normalised


def _is_dry_tyre_compound(compound: Optional[str]) -> bool:
    if not compound:
        return False
    normalised = compound.strip().lower().replace("_", " ").replace("-", " ")
    if normalised in {"unknown", "none", "---"}:
        return False
    return not _is_wet_tyre_compound(normalised)


def _sector_loss_advice(ref_row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    worst_sector = _worst_sector_loss(ref_row)
    if not worst_sector:
        return None

    loss_ms = _num(worst_sector.get("loss_ms"))
    if loss_ms is None or loss_ms < 450:
        return None

    sector_label = str(worst_sector["label"])
    priority = "warning" if loss_ms >= 900 else "advisory"
    return _item(
        item_id=f"pace-sector-loss-{worst_sector['key']}",
        category="pace",
        priority=priority,
        title=f"{sector_label.title()} pace loss",
        message=(
            f"{sector_label.title()} cost {_format_gap_ms(loss_ms)} versus your best lap. "
            "Check braking references and throttle pickup there."
        ),
        voice_callout=f"{sector_label.title()} is costing {_format_gap_ms(loss_ms)}. Clean braking and exit.",
        cooldown_key=f"pace:sector_loss:{worst_sector['key']}",
        evidence=[
            f"{worst_sector['key']}-last={_format_gap_ms(worst_sector['last_ms'])}",
            f"{worst_sector['key']}-best={_format_gap_ms(worst_sector['best_ms'])}",
            f"{worst_sector['key']}-loss={_format_gap_ms(loss_ms)}",
        ],
        metrics={
            "sector": worst_sector["key"],
            "sector_label": sector_label,
            "sector_loss_ms": loss_ms,
            "last_sector_ms": worst_sector["last_ms"],
            "best_sector_ms": worst_sector["best_ms"],
        },
    )


def _worst_sector_loss(ref_row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    losses = _sector_losses(ref_row)
    if not losses:
        return None
    return max(losses, key=lambda item: item["loss_ms"])


def _sector_losses(ref_row: Dict[str, Any]) -> List[Dict[str, Any]]:
    lap_info = _dict(ref_row.get("lap-info", {}))
    last_lap = _dict(lap_info.get("last-lap", {}))
    best_lap = _dict(lap_info.get("best-lap", {}))
    if last_lap.get("is-valid") is False or best_lap.get("is-valid") is False:
        return []

    sectors = (
        ("sector_1", "sector 1", "s1-time-ms"),
        ("sector_2", "sector 2", "s2-time-ms"),
        ("sector_3", "sector 3", "s3-time-ms"),
    )
    losses: List[Dict[str, Any]] = []
    for key, label, field in sectors:
        last_ms = _num(last_lap.get(field))
        best_ms = _num(best_lap.get(field))
        if last_ms is None or best_ms is None or last_ms <= 0 or best_ms <= 0:
            continue
        loss_ms = last_ms - best_ms
        if loss_ms <= 0:
            continue
        losses.append({
            "key": key,
            "label": label,
            "last_ms": last_ms,
            "best_ms": best_ms,
            "loss_ms": loss_ms,
        })
    return losses


def _tyre_wear_rate_advice(
    tyre: Dict[str, Any],
    compound: Optional[str],
    tyre_age: Any,
) -> Optional[Dict[str, Any]]:
    prediction = _dict(tyre.get("wear-prediction", {}))
    if prediction.get("status") is not True:
        return None

    rates = _tyre_wear_rates(prediction)
    if len(rates) < 3:
        return None

    fastest_tyre, fastest_rate = max(rates.items(), key=lambda item: item[1])
    other_rates = [rate for tyre_name, rate in rates.items() if tyre_name != fastest_tyre]
    other_average = sum(other_rates) / len(other_rates)
    rate_delta = fastest_rate - other_average
    if fastest_rate < 2.8 or rate_delta < 0.6:
        return None

    current = _dict(tyre.get("current-wear", {}))
    current_wear = _num(current.get(f"{fastest_tyre}-wear"))
    priority = "warning" if fastest_rate >= 3.5 or (current_wear is not None and current_wear >= 55) else "advisory"
    labelled_tyre = _label_tyre(fastest_tyre)
    return _item(
        item_id=f"tyres-wear-rate-{fastest_tyre}",
        category="tyres",
        priority=priority,
        title="Tyre wear rate",
        message=(
            f"{labelled_tyre} is wearing {_format_rate_delta(rate_delta)} per lap faster than the other tyres. "
            "Reduce wheelspin and sliding on exits."
        ),
        voice_callout=f"{labelled_tyre} is wearing faster. Smooth traction on exits.",
        cooldown_key=f"tyres:wear_rate:{fastest_tyre}",
        evidence=[
            f"compound={compound}",
            f"tyre-age-laps={tyre_age}",
            f"{fastest_tyre}-wear-rate={fastest_rate:.2f}%/lap",
            f"other-tyres-average-wear-rate={other_average:.2f}%/lap",
        ],
        metrics={
            "fastest_wear_rate_tyre": fastest_tyre,
            "fastest_wear_rate_pct_per_lap": fastest_rate,
            "other_tyres_average_wear_rate_pct_per_lap": other_average,
            "wear_rate_delta_pct_per_lap": rate_delta,
            "current_wear_pct": current_wear,
        },
    )


def _tyre_stint_forecast_advice(
    tyre: Dict[str, Any],
    compound: Optional[str],
    tyre_age: Any,
    available_wear: Dict[str, float],
) -> Optional[Dict[str, Any]]:
    forecast = _tyre_stint_forecast(tyre, available_wear)
    if not forecast:
        return None

    puncture = forecast["puncture_risk"]
    if (
        puncture["current_wear_pct"] < _TYRE_PUNCTURE_RISK_WEAR_PCT
        and puncture["laps_to_threshold"] <= _TYRE_PUNCTURE_WINDOW_LAPS
    ):
        priority = "critical" if puncture["laps_to_threshold"] <= 1.0 else "warning"
        tyre_label = _label_tyre(puncture["tyre"])
        return _item(
            item_id=f"tyres-puncture-window-{puncture['tyre']}",
            category="tyres",
            priority=priority,
            title="Tyre puncture forecast",
            message=(
                f"{tyre_label} is projected to reach {_TYRE_PUNCTURE_RISK_WEAR_PCT:.0f}% wear in "
                f"{puncture['laps_to_threshold']:.1f} laps. Box or protect the tyre before puncture risk arrives."
            ),
            voice_callout=(
                f"{tyre_label} reaches puncture risk in about {puncture['laps_to_threshold']:.1f} laps. "
                "Protect it or box."
            ),
            cooldown_key=f"tyres:puncture_window:{puncture['tyre']}",
            evidence=[
                f"compound={compound}",
                f"tyre-age-laps={tyre_age}",
                f"{puncture['tyre']}-wear={puncture['current_wear_pct']:.1f}%",
                f"{puncture['tyre']}-wear-rate={puncture['wear_rate_pct_per_lap']:.2f}%/lap",
                f"projected-laps-to-80-wear={puncture['laps_to_threshold']:.1f}",
            ],
            metrics={
                "projected_tyre": puncture["tyre"],
                "projected_threshold_pct": _TYRE_PUNCTURE_RISK_WEAR_PCT,
                "projected_laps_to_threshold": puncture["laps_to_threshold"],
                "current_wear_pct": puncture["current_wear_pct"],
                "wear_rate_pct_per_lap": puncture["wear_rate_pct_per_lap"],
            },
        )

    stint = forecast["stint_limit"]
    if (
        stint["current_wear_pct"] >= _TYRE_STINT_LIMIT_WEAR_PCT
        or stint["laps_to_threshold"] > _TYRE_STINT_WINDOW_LAPS
    ):
        return None

    priority = "warning" if stint["laps_to_threshold"] <= 2.0 else "advisory"
    tyre_label = _label_tyre(stint["tyre"])
    return _item(
        item_id=f"tyres-stint-window-{stint['tyre']}",
        category="tyres",
        priority=priority,
        title="Tyre stint forecast",
        message=(
            f"{tyre_label} is projected to reach {_TYRE_STINT_LIMIT_WEAR_PCT:.0f}% wear in "
            f"{stint['laps_to_threshold']:.1f} laps. Start planning the end of this stint."
        ),
        voice_callout=(
            f"{tyre_label} reaches stint limit in about {stint['laps_to_threshold']:.1f} laps. "
            "Start planning the stop."
        ),
        cooldown_key=f"tyres:stint_window:{stint['tyre']}",
        evidence=[
            f"compound={compound}",
            f"tyre-age-laps={tyre_age}",
            f"{stint['tyre']}-wear={stint['current_wear_pct']:.1f}%",
            f"{stint['tyre']}-wear-rate={stint['wear_rate_pct_per_lap']:.2f}%/lap",
            f"projected-laps-to-70-wear={stint['laps_to_threshold']:.1f}",
        ],
        metrics={
            "projected_tyre": stint["tyre"],
            "projected_threshold_pct": _TYRE_STINT_LIMIT_WEAR_PCT,
            "projected_laps_to_threshold": stint["laps_to_threshold"],
            "current_wear_pct": stint["current_wear_pct"],
            "wear_rate_pct_per_lap": stint["wear_rate_pct_per_lap"],
        },
    )


def _tyre_stint_forecast(
    tyre: Dict[str, Any],
    available_wear: Dict[str, float],
) -> Optional[Dict[str, Dict[str, Any]]]:
    prediction = _dict(tyre.get("wear-prediction", {}))
    if prediction.get("status") is not True:
        return None
    rates = _tyre_wear_rates(prediction)
    if not rates or not available_wear:
        return None

    stint_projections = []
    puncture_projections = []
    for tyre_name, current_wear in available_wear.items():
        rate = rates.get(tyre_name)
        if rate is None or rate <= 0:
            continue
        stint_projections.append(_tyre_threshold_projection(
            tyre_name,
            current_wear,
            rate,
            _TYRE_STINT_LIMIT_WEAR_PCT,
        ))
        puncture_projections.append(_tyre_threshold_projection(
            tyre_name,
            current_wear,
            rate,
            _TYRE_PUNCTURE_RISK_WEAR_PCT,
        ))

    if not stint_projections or not puncture_projections:
        return None
    return {
        "stint_limit": min(stint_projections, key=lambda item: item["laps_to_threshold"]),
        "puncture_risk": min(puncture_projections, key=lambda item: item["laps_to_threshold"]),
    }


def _tyre_threshold_projection(
    tyre_name: str,
    current_wear: float,
    wear_rate: float,
    threshold_pct: float,
) -> Dict[str, Any]:
    laps_to_threshold = 0.0 if current_wear >= threshold_pct else (threshold_pct - current_wear) / wear_rate
    return {
        "tyre": tyre_name,
        "current_wear_pct": current_wear,
        "wear_rate_pct_per_lap": wear_rate,
        "threshold_pct": threshold_pct,
        "laps_to_threshold": max(0.0, laps_to_threshold),
    }


def _tyre_wear_rates(prediction: Dict[str, Any]) -> Dict[str, float]:
    rates = _dict(prediction.get("rate", {}))
    return {
        name: value
        for name, value in ((key, _num(val)) for key, val in rates.items())
        if value is not None
    }


def _format_rate_delta(value: float) -> str:
    return f"{value:.1f}%"


def _filter_and_sort_advice(
    advice: List[Dict[str, Any]],
    focus: str,
    max_items: int,
) -> List[Dict[str, Any]]:
    if focus != _CATEGORY_ALL:
        advice = [item for item in advice if isinstance(item, dict) and item.get("category") == focus]
    return sorted(
        [item for item in advice if isinstance(item, dict)],
        key=lambda item: (_PRIORITY_RANK.get(item.get("priority"), 99), item.get("id", "")),
    )[:max_items]


def _build_brief_text(advice: List[Dict[str, Any]]) -> str:
    if not advice:
        return "No high-priority race engineer calls right now. Keep the rhythm."
    return " ".join(item["voice_callout"] for item in advice)


def _item(
    item_id: str,
    category: str,
    priority: str,
    title: str,
    message: str,
    voice_callout: str,
    cooldown_key: str,
    evidence: List[str],
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "id": item_id,
        "category": category,
        "priority": priority,
        "title": title,
        "message": message,
        "voice_callout": voice_callout,
        "cooldown_key": cooldown_key,
        "evidence": evidence,
        "metrics": metrics,
    }


def _last_lap_ms(row: Dict[str, Any]) -> Optional[float]:
    return _num(_dict(_dict(row.get("lap-info", {})).get("last-lap", {})).get("lap-time-ms"))


def _nearby_last_lap_ms(nearby: Dict[str, Any]) -> Optional[float]:
    lap = nearby.get("last_lap")
    if not lap:
        return None
    return _num(nearby.get("last_lap_ms"))


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_or_none(value: Any) -> Optional[int]:
    number = _num(value)
    if number is None or not float(number).is_integer():
        return None
    return int(number)


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _safe_text(value: Any, *, max_len: int = 80) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    if not text:
        return None
    if len(text) > max_len:
        return f"{text[:max_len - 3]}..."
    return text


def _format_gap_ms(ms: Optional[float]) -> str:
    if ms is None:
        return "unavailable"
    return f"{abs(ms) / 1000.0:.1f}s"


def _is_safety_car_active(status: Optional[str]) -> bool:
    if not status:
        return False
    normalised = status.strip().lower().replace("_", " ").replace("-", " ")
    inactive_tokens = {"none", "no safety car", "safety car status.none", "no safety car status"}
    if normalised in inactive_tokens:
        return False
    return "safety" in normalised or "vsc" in normalised or "virtual" in normalised


def _pit_loss_ms(value: Any) -> Optional[float]:
    number = _num(value)
    if number is None or number <= 0:
        return None
    if number > 1000:
        return number
    return number * 1000.0


def _fuel_burn_delta_kg(target: Optional[float], last_used: Optional[float]) -> Optional[float]:
    if target is None or last_used is None or target <= 0 or last_used <= 0:
        return None
    return last_used - target


def _format_lap_time_ms(ms: Optional[float]) -> Optional[str]:
    if ms is None or ms <= 0:
        return None
    total_ms = int(round(ms))
    minutes = total_ms // 60000
    seconds_ms = total_ms % 60000
    seconds = seconds_ms // 1000
    millis = seconds_ms % 1000
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _label_tyre(name: str) -> str:
    return name.replace("-", " ").title()
