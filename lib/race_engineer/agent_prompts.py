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

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# -------------------------------------- CONSTANTS ---------------------------------------------------------------------

CATEGORY_ALL = "all"
CATEGORY_REVIEW = "review"

ADVICE_CATEGORIES: Tuple[str, ...] = (
    "pace",
    "tyres",
    "fuel",
    "ers",
    "damage",
    "weather",
    "strategy",
    "race_control",
    "driving_coach",
)

PROMPT_CATEGORIES: Tuple[str, ...] = (*ADVICE_CATEGORIES, CATEGORY_REVIEW)
PROMPT_OVERRIDE_FIELDS: Tuple[str, ...] = (
    "role",
    "system_prompt",
    "evidence_contract",
    "call_policy",
    "output_contract",
)
DEFAULT_AGENT_PROMPTS_FILE_ENV_VAR = "PNG_RACE_ENGINEER_AGENT_PROMPTS_FILE"

BASE_SYSTEM_RULES = (
    "Use only the supplied evidence and metrics.",
    "Never invent tyre state, lap deltas, damage, weather, setup, flags, or strategy facts.",
    "Prefer one concrete action over general encouragement.",
    "Keep voice callouts short enough to say during driving.",
    "If evidence is missing or contradictory, say that no call should be made.",
)

OUTPUT_CONTRACT = (
    "Return a single JSON object with id, priority, title, message, voice_callout, "
    "cooldown_key, evidence, and metrics. priority must be critical, warning, advisory, or info."
)

# -------------------------------------- CLASSES -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RaceEngineerAgentPrompt:
    """Prompt contract for one race engineer advisor role."""

    category: str
    role: str
    system_prompt: str
    evidence_contract: str
    call_policy: str
    output_contract: str = OUTPUT_CONTRACT

    def as_text(self) -> str:
        """Return a compact prompt suitable for Codex or an LLM agent."""

        rules = " ".join(BASE_SYSTEM_RULES)
        return (
            f"Role: {self.role}\n"
            f"Category: {self.category}\n"
            f"System: {self.system_prompt} {rules}\n"
            f"Evidence: {self.evidence_contract}\n"
            f"Call policy: {self.call_policy}\n"
            f"Output: {self.output_contract}"
        )

    def as_dict(self) -> Dict[str, str]:
        """Return a structured prompt spec for programmatic consumers."""

        return {
            "category": self.category,
            "role": self.role,
            "system_prompt": self.system_prompt,
            "base_rules": " ".join(BASE_SYSTEM_RULES),
            "evidence_contract": self.evidence_contract,
            "call_policy": self.call_policy,
            "output_contract": self.output_contract,
        }


# -------------------------------------- DATA --------------------------------------------------------------------------


AGENT_PROMPTS: Dict[str, RaceEngineerAgentPrompt] = {
    "pace": RaceEngineerAgentPrompt(
        category="pace",
        role="Pace Engineer",
        system_prompt="Compare lap pace, sector signals, gaps, and race position to decide whether to attack, hold, or defend.",
        evidence_contract="Use only current lap delta, completed lap times, sector times, gap ahead, gap behind, and positions.",
        call_policy="Call pace only when the delta is large enough to change the driver's next lap or battle plan.",
    ),
    "tyres": RaceEngineerAgentPrompt(
        category="tyres",
        role="Tyre Engineer",
        system_prompt="Assess tyre wear, compound, age, temperatures, and projected stint health.",
        evidence_contract="Use only compound, tyre age, per-corner wear, average wear, wear prediction, and temperature evidence.",
        call_policy="Warn for puncture risk, stint-life risk, asymmetric wear, overheating, or traction-preservation needs.",
    ),
    "fuel": RaceEngineerAgentPrompt(
        category="fuel",
        role="Fuel Engineer",
        system_prompt="Convert fuel surplus, burn, and target rate into push, hold, or save instructions.",
        evidence_contract="Use only fuel surplus, fuel remaining laps, last lap fuel used, and target burn evidence.",
        call_policy="Call fuel when the driver should start saving, can stop saving, or has enough surplus to push.",
    ),
    "ers": RaceEngineerAgentPrompt(
        category="ers",
        role="ERS and Battle Engineer",
        system_prompt="Plan battery deployment and recovery around attack, defence, DRS, and overtake availability.",
        evidence_contract="Use only ERS percentage, deploy mode, DRS windows, overtake availability, and nearby gap evidence.",
        call_policy="Call ERS when battery state changes the next straight, DRS attack, or defence decision.",
    ),
    "damage": RaceEngineerAgentPrompt(
        category="damage",
        role="Damage Engineer",
        system_prompt="Explain car damage and expected handling impact without overstating unmeasured pace loss.",
        evidence_contract="Use only wing, floor, diffuser, sidepod, gearbox, engine, tyre, brake, DRS, and ERS fault evidence.",
        call_policy="Call damage when balance, reliability, or pit urgency should change immediately.",
    ),
    "weather": RaceEngineerAgentPrompt(
        category="weather",
        role="Weather Engineer",
        system_prompt="Track current conditions, forecast transitions, rain probability, and track-temperature trends.",
        evidence_contract="Use only current weather, forecast samples, rain percentage, air temperature, and track temperature evidence.",
        call_policy="Call weather when rain, drying conditions, or a meaningful track-temperature shift changes tyre or stint planning.",
    ),
    "strategy": RaceEngineerAgentPrompt(
        category="strategy",
        role="Strategy Engineer",
        system_prompt="Combine lap progress, pit windows, tyre state, traffic, weather, race control, and battle context into strategic calls.",
        evidence_contract="Use only lap, pit window, tyre, gap, position, weather forecast, safety car, flag, and penalty evidence.",
        call_policy="Call strategy when the pit window, traffic, weather, safety car, tyre state, or penalties make a decision timely.",
    ),
    "race_control": RaceEngineerAgentPrompt(
        category="race_control",
        role="Race Control Engineer",
        system_prompt="Track flags, safety car state, penalties, warnings, invalid laps, and session state.",
        evidence_contract="Use only FIA flag, safety car, warning, penalty, lap validity, session, and event evidence.",
        call_policy="Call race control when compliance or immediate driving behaviour should change.",
    ),
    "driving_coach": RaceEngineerAgentPrompt(
        category="driving_coach",
        role="Driving Coach",
        system_prompt="Compare braking, throttle, steering, speed, gear, and lap-distance traces against clean references.",
        evidence_contract="Use only binned trace evidence by lap distance, clean reference laps, sector deltas, and track segment names.",
        call_policy="Call coaching only when a repeatable driver input pattern is visible, such as brake/throttle overlap, early braking, long coasting, or poor throttle pickup.",
    ),
    CATEGORY_REVIEW: RaceEngineerAgentPrompt(
        category=CATEGORY_REVIEW,
        role="Review Agent",
        system_prompt="Reject unsupported, stale, unsafe, verbose, or contradictory race engineer calls before they reach the driver.",
        evidence_contract="Use the candidate advice item, its evidence list, metrics, category, priority, and cooldown key.",
        call_policy="Approve only if the call is evidence-backed, short enough for driving, and tied to a concrete next action.",
        output_contract="Return approved true or false, reasons, and any safer replacement text. Do not add new facts.",
    ),
}

# -------------------------------------- FUNCTIONS ---------------------------------------------------------------------


def get_agent_prompt_texts(
    focus: str = CATEGORY_ALL,
    *,
    include_review: bool = True,
    prompt_overrides: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, str]:
    """Return prompt text by category."""

    prompts = _prompt_map(prompt_overrides)
    return {
        category: prompts[category].as_text()
        for category in _selected_prompt_categories(focus, include_review=include_review)
    }


def get_agent_prompt_specs(
    focus: str = CATEGORY_ALL,
    *,
    include_review: bool = True,
    prompt_overrides: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, Dict[str, str]]:
    """Return structured prompt specs by category."""

    prompts = _prompt_map(prompt_overrides)
    return {
        category: prompts[category].as_dict()
        for category in _selected_prompt_categories(focus, include_review=include_review)
    }


def load_agent_prompt_overrides(path: str) -> Dict[str, Dict[str, str]]:
    """Load category prompt overrides from a JSON file."""

    path_text = str(path or "").strip()
    if not path_text:
        return {}
    with Path(path_text).expanduser().open("r", encoding="utf-8") as file_obj:
        data = json.load(file_obj)
    return normalise_agent_prompt_overrides(data)


def build_agent_prompt_override_template() -> Dict[str, Any]:
    """Build an editable prompt override template for every advisor category."""

    return {
        "schema": "pits-n-giggles.race-engineer.agent-prompts.v1",
        "description": (
            "Edit only the prompt text you want to override. "
            "The race engineer will validate category and field names before use."
        ),
        "allowed_fields": list(PROMPT_OVERRIDE_FIELDS),
        "prompts": {
            category: {
                field: value
                for field, value in AGENT_PROMPTS[category].as_dict().items()
                if field in PROMPT_OVERRIDE_FIELDS
            }
            for category in PROMPT_CATEGORIES
        },
    }


def save_agent_prompt_override_template(path: str, *, overwrite: bool = False) -> str:
    """Write an editable agent prompt override template to disk."""

    path_text = str(path or "").strip()
    if not path_text:
        raise ValueError("Agent prompt template path is required.")
    target = Path(path_text).expanduser()
    if target.exists() and not overwrite:
        raise FileExistsError(f"Agent prompt template already exists: {target}")
    if target.parent != Path("."):
        target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as file_obj:
        json.dump(build_agent_prompt_override_template(), file_obj, indent=4)
        file_obj.write("\n")
    return str(target)


def load_agent_prompt_overrides_from_env(
        env_var: str = DEFAULT_AGENT_PROMPTS_FILE_ENV_VAR) -> Dict[str, Dict[str, str]]:
    """Load category prompt overrides from the configured environment variable."""

    path = os.environ.get(env_var, "")
    return load_agent_prompt_overrides(path)


def normalise_agent_prompt_overrides(value: Any) -> Dict[str, Dict[str, str]]:
    """Validate and normalise user-provided prompt override data."""

    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValueError("Agent prompt overrides must be a JSON object.")

    raw_prompts = value.get("prompts", value)
    if not isinstance(raw_prompts, dict):
        raise ValueError("Agent prompt overrides 'prompts' must be an object.")

    overrides: Dict[str, Dict[str, str]] = {}
    for raw_category, raw_fields in raw_prompts.items():
        category = str(raw_category or "").strip().lower().replace("-", "_")
        if category not in PROMPT_CATEGORIES:
            raise ValueError(f"Unknown race engineer prompt category: {raw_category}")
        if not isinstance(raw_fields, dict):
            raise ValueError(f"Prompt override for {category} must be an object.")

        fields: Dict[str, str] = {}
        for raw_field, raw_text in raw_fields.items():
            field = str(raw_field or "").strip()
            if field not in PROMPT_OVERRIDE_FIELDS:
                raise ValueError(f"Unknown prompt override field for {category}: {raw_field}")
            text = _safe_prompt_override_text(raw_text)
            if text:
                fields[field] = text
        if fields:
            overrides[category] = fields
    return overrides


def normalise_agent_focus(focus: str) -> str:
    """Normalise an advisor focus name."""

    if not isinstance(focus, str):
        return CATEGORY_ALL
    focus = (focus or CATEGORY_ALL).strip().lower().replace("-", "_")
    if focus == CATEGORY_ALL or focus in PROMPT_CATEGORIES:
        return focus
    return CATEGORY_ALL


def _prompt_map(
        prompt_overrides: Optional[Dict[str, Dict[str, str]]] = None
        ) -> Dict[str, RaceEngineerAgentPrompt]:
    prompts = dict(AGENT_PROMPTS)
    overrides = normalise_agent_prompt_overrides(prompt_overrides or {})
    for category, fields in overrides.items():
        prompts[category] = replace(prompts[category], **fields)
    return prompts


def _safe_prompt_override_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text or None


def _selected_prompt_categories(focus: str, *, include_review: bool) -> List[str]:
    focus = normalise_agent_focus(focus)
    if focus == CATEGORY_ALL:
        categories: Iterable[str] = ADVICE_CATEGORIES
    elif focus == CATEGORY_REVIEW:
        categories = (CATEGORY_REVIEW,)
        include_review = False
    else:
        categories = (focus,)

    selected = list(categories)
    if include_review and CATEGORY_REVIEW not in selected:
        selected.append(CATEGORY_REVIEW)
    return selected
