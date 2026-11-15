"""Astronaut profiles + live state, persisted to a single JSON file."""
from __future__ import annotations

import json
import os
import random
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from engine import Case, KnowledgeBase
from engine.simulator import generate

ROOT = Path(__file__).resolve().parent
DEFAULT_PATH = ROOT / "data" / "state.json"
HISTORY_LIMIT = 300
HISTORY_KEYS = ["heart_rate", "blood_pressure_systolic", "blood_pressure_diastolic", "spo2",
                "skin_temperature", "cabin_co2"]
COLORS = ["#4cc9f0", "#f72585", "#b5e48c", "#ffbe0b", "#9b5de5", "#00f5d4", "#ff7b00", "#80ed99"]

DEFAULT_ASTRONAUTS = [
    {"name": "Alex Morgan", "sex": "male", "age": 38, "role": "Commander"},
    {"name": "Taylor Chen", "sex": "female", "age": 42, "role": "Pilot"},
    {"name": "Jordan Rivera", "sex": "female", "age": 35, "role": "Systems Engineer"},
    {"name": "Sam Patel", "sex": "male", "age": 45, "role": "Mission Scientist"},
]


class ValidationError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, kb: KnowledgeBase, path: Optional[Path] = None):
        self.kb = kb
        self.path = Path(path) if path else DEFAULT_PATH
        self.lock = threading.RLock()
        self.data: dict = {"astronauts": {}}
        self._load()

    # ----------------------------------------------------------- persistence
    def _load(self):
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text("utf-8"))
                return
            except (json.JSONDecodeError, OSError):
                pass
        self.data = {"astronauts": {}}
        for i, base in enumerate(DEFAULT_ASTRONAUTS):
            self.create({**base, "mission_day": 12 + i * 20, "mission_duration_days": 180}, _persist=False)
        self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, self.path)

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _clean_profile(p: dict) -> dict:
        name = str(p.get("name", "")).strip()
        if not name:
            raise ValidationError("Το όνομα είναι υποχρεωτικό.")
        sex = p.get("sex")
        if sex not in ("male", "female"):
            raise ValidationError("Το φύλο πρέπει να είναι 'male' ή 'female'.")
        try:
            age = int(p.get("age", 35))
            day = int(p.get("mission_day", 1))
            dur = int(p.get("mission_duration_days", 180))
        except (TypeError, ValueError):
            raise ValidationError("Ηλικία / ημέρα αποστολής / διάρκεια πρέπει να είναι αριθμοί.")
        if not (18 <= age <= 80):
            raise ValidationError("Η ηλικία πρέπει να είναι 18–80.")
        if not (1 <= dur <= 1500) or not (0 <= day <= 1500):
            raise ValidationError("Μη έγκυρες ημέρες αποστολής.")
        return {"name": name[:60], "sex": sex, "age": age, "role": str(p.get("role", ""))[:60],
                "mission_day": day, "mission_duration_days": dur,
                "astronaut_id": str(p.get("astronaut_id", "")).strip()[:40],
                "medical_record": p.get("medical_record", {}) if isinstance(p.get("medical_record", {}), dict) else {}}

    def _case(self, a: dict) -> Case:
        prof, st = a["profile"], a["state"]
        readings = dict(st["readings"])
        readings["mission_day"] = prof["mission_day"]
        return Case(sex=prof["sex"], symptoms=set(st["symptoms"]), context=set(st["context"]),
                    readings=readings, mission_duration_days=prof["mission_duration_days"])

    def _assess(self, a: dict) -> dict:
        return self.kb.assess(self._case(a))

    def _get(self, aid: str) -> dict:
        a = self.data["astronauts"].get(aid)
        if not a:
            raise KeyError(aid)
        return a

    def _log(self, a: dict, source: str, note: str = ""):
        res = self._assess(a)
        a["history"].append({
            "ts": _now(), "source": source, "note": note, "overall": res["overall"],
            "findings": [{"id": f["rule_id"], "level": f["level"], "private": f["privacy_sensitive"]}
                         for f in res["findings"]],
            "vitals": {k: a["state"]["readings"].get(k) for k in HISTORY_KEYS},
        })
        del a["history"][:-HISTORY_LIMIT]

    # ----------------------------------------------------------------- API
    def list(self) -> list[dict]:
        with self.lock:
            out = []
            for aid, a in self.data["astronauts"].items():
                res = self._assess(a)
                out.append({"id": aid, **a["profile"], "color": a["color"], "overall": res["overall"],
                            "environment_alert": res["environment_alert"], "findings_count": len(res["findings"])})
            return out

    def create(self, profile: dict, _persist: bool = True) -> dict:
        with self.lock:
            clean = self._clean_profile(profile)
            aid = clean.get("astronaut_id") or uuid.uuid4().hex[:8]
            if aid in self.data["astronauts"]:
                aid = uuid.uuid4().hex[:8]
            rng_seed = int(aid, 16) if all(c in "0123456789abcdefABCDEF" for c in aid) else abs(hash(aid)) % (2**31)
            readings = generate(self.kb, clean, "nominal", rng_seed)["readings"]
            # Import baseline values as the initial reference snapshot when supplied.
            baseline = (clean.get("medical_record") or {}).get("pre_flight_baseline", {})
            cv = baseline.get("cardiovascular", {}) if isinstance(baseline, dict) else {}
            mapping = {"heart_rate": cv.get("heart_rate_resting", {}).get("value"),
                       "blood_pressure_systolic": cv.get("blood_pressure_resting", {}).get("systolic"),
                       "blood_pressure_diastolic": cv.get("blood_pressure_resting", {}).get("diastolic"),
                       "spo2": cv.get("spo2_resting", {}).get("value"),
                       "qtc_interval": cv.get("ecg_baseline", {}).get("qtc_interval", {}).get("value")}
            for key, value in mapping.items():
                if isinstance(value, (int, float)):
                    readings[key] = value
            self.data["astronauts"][aid] = {
                "profile": clean, "color": COLORS[len(self.data["astronauts"]) % len(COLORS)],
                "state": {"readings": readings, "symptoms": [], "context": []}, "history": []}
            self._log(self.data["astronauts"][aid], "system", "Δημιουργία προφίλ")
            if _persist:
                self._save()
            return self.get(aid)

    def update_profile(self, aid: str, patch: dict) -> dict:
        with self.lock:
            a = self._get(aid)
            merged = self._clean_profile({**a["profile"], **patch})
            if merged["sex"] != a["profile"]["sex"]:
                a["state"]["readings"] = generate(self.kb, merged, "nominal")["readings"]
            a["profile"] = merged
            self._save()
            return self.get(aid)

    def delete(self, aid: str):
        with self.lock:
            self._get(aid)
            del self.data["astronauts"][aid]
            self._save()

    def get(self, aid: str) -> dict:
        with self.lock:
            a = self._get(aid)
            return {"id": aid, "profile": a["profile"], "color": a["color"], "state": a["state"],
                    "assessment": self._assess(a)}

    def update_state(self, aid: str, payload: dict, source: str = "manual") -> dict:
        """Partial update: symptoms/context replace; readings merge (None removes a key)."""
        with self.lock:
            a = self._get(aid)
            st = a["state"]
            if "symptoms" in payload:
                unknown = set(payload["symptoms"]) - set(self.kb.vocab["symptoms"])
                if unknown:
                    raise ValidationError(f"Άγνωστα συμπτώματα: {sorted(unknown)}")
                st["symptoms"] = sorted(set(payload["symptoms"]))
            if "context" in payload:
                unknown = set(payload["context"]) - set(self.kb.vocab["context"])
                if unknown:
                    raise ValidationError(f"Άγνωστο context: {sorted(unknown)}")
                st["context"] = sorted(set(payload["context"]))
            for k, v in (payload.get("readings") or {}).items():
                if v is None:
                    st["readings"].pop(k, None)
                    continue
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise ValidationError(f"Η τιμή '{k}' πρέπει να είναι αριθμός.")
                st["readings"][k] = v
            self._log(a, source)
            self._save()
            return self.get(aid)

    def simulate(self, aid: str, mode: str, seed: Optional[int] = None, rule_id: Optional[str] = None,
                 level: Optional[str] = None, keep_symptoms: bool = False) -> dict:
        with self.lock:
            a = self._get(aid)
            if seed is None:
                seed = random.randint(0, 2**31 - 1)
            if rule_id and rule_id not in self.kb.rules_by_id:
                raise ValidationError(f"Άγνωστος κανόνας {rule_id}")
            gen = generate(self.kb, a["profile"], mode, seed, rule_id, level)
            st = a["state"]
            st["readings"] = gen["readings"]
            if not keep_symptoms:
                st["symptoms"], st["context"] = gen["symptoms"], gen["context"]
            self._log(a, "simulation", gen["description"])
            self._save()
            out = self.get(aid)
            out["simulation"] = {"mode": mode, "seed": seed, "description": gen["description"]}
            return out

    def reset(self, aid: str) -> dict:
        return self.simulate(aid, "nominal")

    def history(self, aid: str) -> list[dict]:
        with self.lock:
            return list(self._get(aid)["history"])
