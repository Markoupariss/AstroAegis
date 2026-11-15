import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine import Case, KnowledgeBase  # noqa: E402
from engine.simulator import MODES, build_case_for_rule, generate, nominal_readings  # noqa: E402
import random  # noqa: E402

KB = KnowledgeBase()
I18N = json.loads((ROOT / "data" / "i18n_el.json").read_text("utf-8"))


def case_from(sex, sol, extra=None):
    readings = dict(sol["readings"])
    readings.update(extra or {})
    return Case(sex=sex, symptoms=set(sol.get("symptoms", [])), context=set(sol.get("context", [])), readings=readings)


def A(sex="male", symptoms=(), context=(), **readings):
    return KB.assess(Case(sex=sex, symptoms=set(symptoms), context=set(context), readings=readings))


def ids(a):
    return {f["rule_id"]: f for f in a["findings"]}


class DataIntegrity(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(len(KB.rules), 32)
        self.assertEqual(len({r["id"] for r in KB.rules}), 32)

    def test_every_leaf_refers_to_known_vocabulary(self):
        known_derived = set(KB.derived) | {"symptom_duration_hours", "mission_day"}

        def walk(e):
            for k in ("all", "any"):
                for x in e.get(k, []):
                    walk(x)
            if "not" in e:
                walk(e["not"])
            if "at_least" in e:
                for x in e["at_least"]["of"]:
                    walk(x)
            if "symptom" in e:
                self.assertIn(e["symptom"], KB.vocab["symptoms"])
            if "context" in e:
                self.assertIn(e["context"], KB.vocab["context"])
            if "signal" in e:
                if "level" in e:
                    self.assertIn(e["signal"], KB.signals)
                    self.assertIsNotNone(KB.signals[e["signal"]].get(e["level"]), e)
                else:
                    self.assertIn(e["signal"], known_derived, e)

        for r in KB.rules:
            for expr in r["levels"].values():
                walk(expr)
            for key in ("supporting_evidence",):
                if r.get(key):
                    walk(r[key])
            if r.get("red_flags"):
                walk(r["red_flags"]["expression"])

    def test_greek_coverage(self):
        self.assertEqual(set(KB.vocab["symptoms"]), set(I18N["symptoms"]))
        self.assertEqual(set(KB.vocab["context"]), set(I18N["context"]))
        self.assertEqual({r["id"] for r in KB.rules}, set(I18N["conditions"]))
        grouped = [s for g in I18N["symptom_groups"] for s in g["symptoms"]]
        self.assertEqual(sorted(grouped), sorted(KB.vocab["symptoms"]))
        for item in KB.reading_keys():
            self.assertIn(item["key"], I18N["signals"])


class AllRulesAllLevels(unittest.TestCase):
    def test_each_level_of_each_rule_fires(self):
        for sex in ("male", "female"):
            for r in KB.rules:
                for lvl in r["levels"]:
                    with self.subTest(rule=r["id"], level=lvl, sex=sex):
                        sol = build_case_for_rule(KB, r["id"], lvl, sex, seed=7)
                        self.assertIsNotNone(sol, "solver could not build a case")
                        res = KB.evaluate_rule(r, case_from(sex, sol))
                        self.assertIn(lvl, res["triggered"])


class ClinicalBehaviour(unittest.TestCase):
    def test_nominal_is_normal_for_many_seeds(self):
        for sex in ("male", "female"):
            for seed in range(150):
                r = nominal_readings(KB, sex, random.Random(seed))
                a = KB.assess(Case(sex=sex, readings=r))
                self.assertEqual(a["overall"], "NORMAL", (sex, seed, [s for s in a["signals"] if s["status"] != "normal"]))
                self.assertEqual(a["findings"], [])

    def test_thresholds(self):
        a = A(spo2=91)
        self.assertEqual(a["overall"], "URGENT")
        self.assertEqual([s["status"] for s in a["signals"]], ["critical"])
        self.assertEqual(A(spo2=94)["signals"][0]["status"], "caution")
        self.assertEqual(A(spo2=97)["overall"], "NORMAL")
        self.assertEqual(A(skin_temperature=37.5)["overall"], "MONITOR")
        self.assertEqual(A(heart_rate=110)["signals"][0]["status"], "critical")  # inclusive (NASA cutoff)
        self.assertTrue(A(heart_rate=110)["info_alerts"])
        self.assertEqual(A(heart_rate=100)["signals"][0]["status"], "normal")
        self.assertEqual(A(heart_rate=101)["signals"][0]["status"], "caution")
        self.assertEqual(A(heart_rate=39)["signals"][0]["status"], "critical")

    def test_sex_specific_limits(self):
        self.assertEqual(A("male", hemoglobin=12.5)["signals"][0]["status"], "caution")
        self.assertEqual(A("female", hemoglobin=12.5)["signals"][0]["status"], "normal")
        self.assertEqual(A("male", qtc_interval=455)["signals"][0]["status"], "caution")
        self.assertEqual(A("female", qtc_interval=455)["signals"][0]["status"], "normal")

    def test_nuclear_limit_scales_with_mission(self):
        a = KB.assess(Case(readings={"nuclear_source_dose": 12}, mission_duration_days=182))
        self.assertEqual(a["signals"][0]["status"], "critical")  # limit ~10 mSv for 6 months
        a = KB.assess(Case(readings={"nuclear_source_dose": 12}, mission_duration_days=365))
        self.assertEqual(a["signals"][0]["status"], "normal")

    def test_anaphylaxis_replaces_mild_allergy(self):
        a = ids(A(symptoms=["pruritus", "airway_edema"], context=["suspected_allergen_exposure"]))
        self.assertEqual(a["C02"]["level"], "EMERGENCY")
        self.assertNotIn("C01", a)
        b = ids(A(symptoms=["pruritus"], context=["suspected_allergen_exposure"]))
        self.assertEqual(b["C01"]["level"], "SUSPECTED")
        self.assertIsNotNone(a["C02"]["medication"]["specific_dose"])

    def test_co2_environment_alert_without_symptoms(self):
        a = A(cabin_co2=3.2)
        self.assertTrue(a["environment_alert"])
        self.assertIn("ENVIRONMENT_ALERT", ids(a)["C05"]["channels"])
        self.assertIsNone(ids(a)["C05"]["numeric_level"])
        b = A(symptoms=["headache"], cabin_co2=3.2)
        self.assertEqual(ids(b)["C05"]["level"], "SUSPECTED")
        self.assertNotIn("C25", ids(b))  # overlap collapsed into the specific code

    def test_red_flags(self):
        a = ids(A(symptoms=["low_back_pain", "leg_weakness"], context=["recent_microgravity_transition"]))
        self.assertTrue(a["C03"]["red_flag_only"])
        self.assertEqual(a["C03"]["level"], "URGENT")
        self.assertEqual(a["C03"]["steps"], [])
        b = ids(A(symptoms=["low_back_pain"], context=["recent_microgravity_transition"]))
        self.assertEqual(b["C03"]["level"], "SUSPECTED")
        # red-flag symptom alone must not create a C03 finding
        self.assertNotIn("C03", ids(A(symptoms=["leg_weakness"])))
        c = ids(A(symptoms=["headache", "sudden_severe_headache"], context=["recent_microgravity_transition"]))
        self.assertEqual(c["C25"]["level"], "EMERGENCY")
        self.assertTrue(c["C06"]["red_flag_only"])

    def test_constipation_overlap_and_escalation(self):
        a = ids(A(symptoms=["hard_stools", "straining"], context=["recent_microgravity_transition"]))
        self.assertIn("C04", a)
        self.assertNotIn("C15", a)
        b = ids(A(symptoms=["hard_stools", "straining", "severe_abdominal_pain"], context=["recent_microgravity_transition"]))
        self.assertEqual(b["C04"]["level"], "URGENT")   # red flag promotes the specific code
        self.assertTrue(b["C04"]["red_flag"])
        self.assertNotIn("C15", b)
        c = ids(A(symptoms=["hard_stools", "straining", "severe_abdominal_pain"]))
        self.assertEqual(c["C15"]["level"], "URGENT")
        d = ids(A(symptoms=["severe_abdominal_pain"]))      # warning sign only, no benign self-care steps
        self.assertTrue(d["C15"]["escalation_only"])
        self.assertEqual(d["C15"]["steps"], [])

    def test_escalation_only_is_flagged(self):
        a = ids(A(spo2=94))
        self.assertEqual(a["C28"]["level"], "URGENT")
        self.assertTrue(a["C28"]["escalation_only"])
        b = ids(A(symptoms=["intense_fear", "palpitations", "sweating"], context=["medical_causes_excluded"]))
        self.assertEqual(b["C28"]["level"], "SUSPECTED")
        self.assertFalse(b["C28"]["escalation_only"])

    def test_qt_warning_for_ondansetron(self):
        a = ids(A("female", symptoms=["nausea"], context=["recent_microgravity_transition"], qtc_interval=470))
        self.assertEqual(a["C08"]["medication"]["warnings"][0]["code"], "qt_caution")
        b = ids(A("male", symptoms=["nausea"], context=["recent_microgravity_transition"]))
        self.assertEqual(b["C08"]["medication"]["warnings"][0]["code"], "qt_missing")

    def test_orthostatic_supporting_and_syncope(self):
        a = ids(A(symptoms=["presyncope"], context=["gravity_re_exposure"], systolic_bp_drop_on_standing=25))
        self.assertTrue(a["C14"]["supporting_evidence_met"])
        self.assertEqual(ids(A(symptoms=["syncope"]))["C14"]["level"], "EMERGENCY")

    def test_mental_health_private_and_emergency(self):
        a = ids(A(symptoms=["suicidal_ideation"]))
        self.assertEqual(a["C26"]["level"], "EMERGENCY")
        self.assertTrue(a["C26"]["privacy_sensitive"])
        self.assertEqual(ids(A(symptoms=["conflict_reported"]))["C31"]["level"], "TEAM_SUPPORT")

    def test_overall_priority(self):
        a = A(symptoms=["syncope"], heart_rate=105)
        self.assertEqual(a["overall"], "EMERGENCY")
        self.assertEqual(a["findings"][0]["numeric_level"], "EMERGENCY")


class Simulator(unittest.TestCase):
    def test_modes(self):
        profile = {"sex": "female", "mission_day": 10, "mission_duration_days": 180}
        for mode in MODES:
            for seed in range(25):
                st = generate(KB, profile, mode, seed)
                a = KB.assess(Case(sex="female", symptoms=set(st["symptoms"]), context=set(st["context"]),
                                   readings=st["readings"]))
                if mode == "nominal":
                    self.assertEqual(a["overall"], "NORMAL")
                if mode == "critical":
                    self.assertTrue(a["critical_signals"], (seed, st["readings"]))
                if mode == "mild":
                    self.assertTrue(any(s["status"] == "caution" for s in a["signals"]) or a["findings"], seed)
                if mode == "event":
                    self.assertTrue(a["findings"], (seed, st))

    def test_seed_is_reproducible(self):
        p = {"sex": "male", "mission_day": 5, "mission_duration_days": 180}
        self.assertEqual(generate(KB, p, "event", 42), generate(KB, p, "event", 42))

    def test_specific_event(self):
        p = {"sex": "male", "mission_day": 5, "mission_duration_days": 180}
        st = generate(KB, p, "event", 1, "C02", "EMERGENCY")
        a = KB.assess(Case(sex="male", symptoms=set(st["symptoms"]), context=set(st["context"]), readings=st["readings"]))
        self.assertEqual(ids(a)["C02"]["level"], "EMERGENCY")


class ApiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from server import create_server
        cls.tmp = tempfile.TemporaryDirectory()
        cls.srv = create_server("127.0.0.1", 0, Path(cls.tmp.name) / "state.json")
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def call(self, method, path, body=None, raw=False):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                data = r.read()
                return r.status, (data if raw else json.loads(data))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_flow(self):
        code, meta = self.call("GET", "/api/meta")
        self.assertEqual(code, 200)
        self.assertEqual(len(meta["rules"]), 32)
        code, lst = self.call("GET", "/api/astronauts")
        self.assertEqual(len(lst), 4)
        self.assertTrue(all(a["overall"] == "NORMAL" for a in lst))
        aid = lst[0]["id"]

        code, d = self.call("PUT", f"/api/astronauts/{aid}/state",
                            {"symptoms": ["pruritus"], "context": ["suspected_allergen_exposure"]})
        self.assertEqual(d["assessment"]["findings"][0]["rule_id"], "C01")
        code, d = self.call("PUT", f"/api/astronauts/{aid}/state", {"readings": {"spo2": 90}})
        self.assertEqual(d["assessment"]["overall"], "URGENT")
        code, d = self.call("PUT", f"/api/astronauts/{aid}/state", {"readings": {"spo2": None}})
        self.assertNotIn("spo2", d["state"]["readings"])
        code, d = self.call("POST", f"/api/astronauts/{aid}/simulate", {"mode": "event", "rule_id": "C11", "seed": 1})
        self.assertEqual(d["assessment"]["overall"], "EMERGENCY")
        code, d = self.call("POST", f"/api/astronauts/{aid}/reset")
        self.assertEqual(d["assessment"]["overall"], "NORMAL")
        code, h = self.call("GET", f"/api/astronauts/{aid}/history")
        self.assertGreaterEqual(len(h), 5)

        code, new = self.call("POST", "/api/astronauts", {"name": "Test <b>", "sex": "male", "age": 40,
                                                          "role": "x", "mission_day": 3, "mission_duration_days": 100})
        self.assertEqual(code, 201)
        self.assertEqual(new["assessment"]["overall"], "NORMAL")
        code, _ = self.call("DELETE", f"/api/astronauts/{new['id']}")
        self.assertEqual(code, 200)

    def test_validation_and_errors(self):
        aid = self.call("GET", "/api/astronauts")[1][0]["id"]
        self.assertEqual(self.call("PUT", f"/api/astronauts/{aid}/state", {"symptoms": ["nope"]})[0], 400)
        self.assertEqual(self.call("PUT", f"/api/astronauts/{aid}/state", {"readings": {"spo2": "x"}})[0], 400)
        self.assertEqual(self.call("POST", "/api/astronauts", {"name": "", "sex": "male"})[0], 400)
        self.assertEqual(self.call("POST", "/api/astronauts", {"name": "A", "sex": "alien"})[0], 400)
        self.assertEqual(self.call("GET", "/api/astronauts/zzz")[0], 404)
        self.assertEqual(self.call("POST", f"/api/astronauts/{aid}/simulate", {"mode": "bogus"})[0], 400)

    def test_static_and_traversal(self):
        code, body = self.call("GET", "/", raw=True)
        self.assertEqual(code, 200)
        self.assertIn(b"Astro Health", body)
        self.assertEqual(self.call("GET", "/app.js", raw=True)[0], 200)
        self.assertEqual(self.call("GET", "/..%2fserver.py")[0], 404)
        self.assertEqual(self.call("GET", "/../server.py")[0], 404)


if __name__ == "__main__":
    unittest.main(verbosity=1)
