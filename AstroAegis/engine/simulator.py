"""Random sensor generator + constructive test-case builder.

`build_case_for_rule` walks a rule's expression tree and builds a minimal set of
symptoms / context / readings that satisfies a given level. It is used both by the
"random event" button in the UI and by the automated tests (every level of every rule).
"""
from __future__ import annotations

import math
import random
from typing import Optional

from .engine import Case, KnowledgeBase, LEVEL_PRIORITY

SENSOR_KEYS = ["heart_rate", "blood_pressure_systolic", "blood_pressure_diastolic", "spo2",
               "skin_temperature", "cabin_co2", "qtc_interval"]
MILD_POOL = SENSOR_KEYS + ["hemoglobin", "hematocrit", "rbc", "wbc", "neutrophils", "lymphocytes",
                           "monocytes", "platelets", "reticulocytes", "d_dimer"]

MODES = ["nominal", "mild", "critical", "chaos", "event"]


def _round(v: float, ref: float) -> float:
    return round(v, 1 if abs(ref) >= 10 else 2)


# ------------------------------------------------------------------ nominal vitals
def nominal_readings(kb: KnowledgeBase, sex: str, rng: random.Random, mission_day: int = 30,
                     mission_duration_days: int = 180) -> dict:
    case = Case(sex=sex, mission_duration_days=mission_duration_days)
    readings: dict = {}
    for item in kb.reading_keys():
        base = item["key"]
        name = kb.signal_name(base, sex)
        limits = kb.limits_for(name, case)
        cb, ca = limits.get("caution_below"), limits.get("caution_above")
        crit_a = limits.get("critical_above")
        if base == "vomiting_episodes":
            v = 0
        elif cb is not None and ca is not None:
            span = ca - cb
            v = rng.uniform(cb + 0.18 * span, ca - 0.18 * span)
        elif cb is not None:                      # low_is_bad (SpO2)
            v = min(100.0, rng.uniform(cb + 1, cb + 4.5))
        else:                                     # high_is_bad: stay well under the first limit
            ref = ca if ca is not None else crit_a
            lo, hi = (0.15, 0.7) if item["category"] == "radiation" else (0.35, 0.85)
            if base == "qtc_interval":
                lo, hi = 0.8, 0.92
            v = rng.uniform(lo * ref, hi * ref)
        readings[base] = int(round(v)) if base in ("heart_rate", "blood_pressure_systolic", "blood_pressure_diastolic",
                                                   "spo2", "platelets") else _round(v, v)
    readings["core_temperature"] = round(rng.uniform(36.4, 37.1), 1)
    readings["watery_stool_count_24h"] = 0
    readings["mission_day"] = mission_day
    return readings


def _beyond(kb: KnowledgeBase, name: str, level: str, case: Case):
    limit = kb.limits_for(name, case)[level]
    d = max(abs(limit) * 0.04, 0.05)
    if level.endswith("_above"):
        v = limit + d
        return math.ceil(v) if abs(limit) >= 10 and float(limit).is_integer() else _round(v, limit)
    v = limit - d
    return math.floor(v) if abs(limit) >= 10 and float(limit).is_integer() else _round(v, limit)


def _into_caution(kb: KnowledgeBase, name: str, case: Case, rng: random.Random):
    limits = kb.limits_for(name, case)
    options = []
    ca, cb = limits.get("caution_above"), limits.get("caution_below")
    if ca is not None:
        top = limits.get("critical_above")
        options.append(ca + (0.4 * (top - ca) if top else abs(ca) * 0.08))
    if cb is not None:
        bot = limits.get("critical_below")
        options.append(cb - (0.4 * (cb - bot) if bot else abs(cb) * 0.08))
    if not options:
        return None
    v = rng.choice(options)
    return _round(v, v)


# ---------------------------------------------------------- constructive solver
class _Unsat(Exception):
    pass


def _satisfy(kb: KnowledgeBase, expr: dict, sex: str, rng: random.Random, case: Case) -> dict:
    out = {"symptoms": set(), "context": set(), "readings": {}}

    def merge(sub):
        out["symptoms"] |= sub["symptoms"]
        out["context"] |= sub["context"]
        out["readings"].update(sub["readings"])

    if "all" in expr:
        for e in expr["all"]:
            merge(_satisfy(kb, e, sex, rng, case))
    elif "any" in expr:
        branches = list(expr["any"])
        rng.shuffle(branches)
        for b in branches:
            try:
                merge(_satisfy(kb, b, sex, rng, case))
                break
            except _Unsat:
                continue
        else:
            raise _Unsat()
    elif "at_least" in expr:
        spec = expr["at_least"]
        branches = list(spec["of"])
        rng.shuffle(branches)
        merged = 0
        for b in branches:
            if merged >= spec["n"]:
                break
            try:
                merge(_satisfy(kb, b, sex, rng, case))
                merged += 1
            except _Unsat:
                continue
        if merged < spec["n"]:
            raise _Unsat()
    elif "not" in expr:
        pass  # nothing to add; checked afterwards by verification
    elif "symptom" in expr:
        out["symptoms"].add(expr["symptom"])
    elif "context" in expr:
        out["context"].add(expr["context"])
    elif "signal" in expr:
        name = expr["signal"]
        base, sx = kb.base_name(name)
        if sx is not None and sx != sex:
            raise _Unsat()
        if "level" in expr:
            out["readings"][base] = _beyond(kb, name, expr["level"], case)
        else:
            op, val = expr["operator"], expr["value"]
            if op == "between":
                out["readings"][base] = (val[0] + val[1]) / 2
            else:
                out["readings"][base] = {"gte": val, "lte": val, "gt": val + 1, "lt": val - 1}[op]
    return out


def build_case_for_rule(kb: KnowledgeBase, rule_id: str, level: str, sex: str = "male",
                        seed: Optional[int] = None, tries: int = 40) -> Optional[dict]:
    """Return {'symptoms','context','readings'} that makes `level` of the rule fire, or None."""
    rule = kb.rules_by_id[rule_id]
    expr = rule["levels"][level]
    rng = random.Random(seed)
    for _ in range(tries):
        base_case = Case(sex=sex)
        try:
            sol = _satisfy(kb, expr, sex, rng, base_case)
        except _Unsat:
            continue
        case = Case(sex=sex, symptoms=set(sol["symptoms"]), context=set(sol["context"]),
                    readings=dict(sol["readings"]))
        if kb.ev(expr, case):
            return {"symptoms": sorted(sol["symptoms"]), "context": sorted(sol["context"]),
                    "readings": sol["readings"]}
    return None


# -------------------------------------------------------------------- generator
def generate(kb: KnowledgeBase, profile: dict, mode: str = "nominal", seed: Optional[int] = None,
             rule_id: Optional[str] = None, level: Optional[str] = None) -> dict:
    """Return a full state {readings, symptoms, context, description}."""
    rng = random.Random(seed)
    sex = profile["sex"]
    duration = int(profile.get("mission_duration_days", 180))
    readings = nominal_readings(kb, sex, rng, int(profile.get("mission_day", 30)), duration)
    case = Case(sex=sex, mission_duration_days=duration)
    state = {"readings": readings, "symptoms": [], "context": [], "description": "Φυσιολογικές τιμές"}

    if mode == "nominal":
        return state

    if mode == "mild":
        for base in rng.sample(MILD_POOL, rng.randint(1, 3)):
            name = kb.signal_name(base, sex)
            v = _into_caution(kb, name, case, rng) if name else None
            if v is not None:
                readings[base] = v
        state["description"] = "Ήπιες αποκλίσεις (ζώνη προσοχής)"
    elif mode == "critical":
        for base in rng.sample(SENSOR_KEYS, rng.randint(1, 2)):
            name = kb.signal_name(base, sex)
            sig = kb.signals[name]
            levels = [l for l in ("critical_above", "critical_below") if sig.get(l) is not None]
            if levels:
                readings[base] = _beyond(kb, name, rng.choice(levels), case)
        state["description"] = "Κρίσιμες τιμές αισθητήρων"
    elif mode == "chaos":
        for base in SENSOR_KEYS:
            name = kb.signal_name(base, sex)
            lo, hi = kb.display_scale(kb.limits_for(name, case), kb.signals[name]["unit"])
            readings[base] = _round(rng.uniform(lo, hi), hi)
        state["description"] = "Εντελώς τυχαίες τιμές (stress test)"
    elif mode == "event":
        candidates = [(r["id"], l) for r in kb.rules for l in r["levels"]]
        if rule_id:
            candidates = [(rule_id, l) for l in kb.rules_by_id[rule_id]["levels"]
                          if level in (None, l)]
        rng.shuffle(candidates)
        for rid, lvl in candidates:
            sol = build_case_for_rule(kb, rid, lvl, sex, rng.randint(0, 10**9))
            if sol:
                readings.update(sol["readings"])
                state["symptoms"], state["context"] = sol["symptoms"], sol["context"]
                state["description"] = f"Περιστατικό {rid} ({lvl})"
                state["rule_id"], state["level"] = rid, lvl
                break
    else:
        raise ValueError(f"Unknown mode: {mode}")
    return state


__all__ = ["generate", "build_case_for_rule", "nominal_readings", "MODES", "LEVEL_PRIORITY"]
