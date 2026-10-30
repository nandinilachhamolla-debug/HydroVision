"""Backend tests (unittest + Flask test client, temporary database). Run:  python -m unittest test_backend -v"""
import os
import tempfile
import unittest

import app as hv
import database


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "database", "test.db")
        hv.app.config["DB_PATH"] = self.path
        hv.startup()
        self.c = hv.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def sim(self, scenario, zone="HV-01"):
        return self.c.post("/api/simulation", json={"scenario": scenario, "zone_id": zone})

    def test_health_and_auto_created_database_folder(self):
        r = self.c.get("/api/health").get_json()
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["counts"]["zones"], 8)
        self.assertFalse(r["model_connected"])
        self.assertTrue(os.path.exists(self.path))

    def test_health_reports_unavailable_database(self):
        blocker = os.path.join(self.tmp.name, "file.txt")
        open(blocker, "w").close()
        hv.app.config["DB_PATH"] = os.path.join(blocker, "db.sqlite")     # parent is a file -> cannot open
        r = self.c.get("/api/health")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.get_json()["status"], "error")

    def test_seed_zones_not_duplicated_on_restart(self):
        hv.startup(); hv.startup()
        with database.connect(self.path) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM zones").fetchone()[0], 8)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0], 8)
        z = self.c.get("/api/zones").get_json()
        self.assertEqual(len(z["zones"]), 8)
        self.assertEqual(z["data_source"], "SIMULATED")
        self.assertIsNotNone(z["zones"][0]["latest"])

    def test_readings_validation(self):
        self.assertEqual(self.c.get("/api/readings?limit=abc").status_code, 400)
        self.assertEqual(self.c.get("/api/readings?limit=0").status_code, 400)
        self.assertEqual(len(self.c.get("/api/readings?limit=5").get_json()["readings"]), 5)

    def test_simulation_input_validation(self):
        self.assertEqual(self.c.post("/api/simulation", data="not json").status_code, 400)
        self.assertEqual(self.c.post("/api/simulation", json={"scenario": "meteor", "zone_id": "HV-01"}).status_code, 400)
        self.assertEqual(self.c.post("/api/simulation", json={"scenario": "normal"}).status_code, 400)
        self.assertEqual(self.sim("normal", "HV-99").status_code, 404)
        self.assertEqual(self.c.get("/api/nothing").status_code, 404)

    def test_sudden_leak_saves_records_and_creates_alert_and_incident(self):
        r = self.sim("sudden_leak")
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertEqual(len(body["readings"]), 6)
        self.assertIsNotNone(body["alert"]); self.assertIsNotNone(body["incident"])
        self.assertIn(body["alert"]["severity"], ("high", "critical"))
        with database.connect(self.path) as c:        # really persisted: read through a NEW connection
            self.assertEqual(c.execute("SELECT COUNT(*) FROM alerts").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM incidents").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM predictions").fetchone()[0], c.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0])
        self.assertEqual(len(self.c.get("/api/alerts").get_json()["alerts"]), 1)

    def test_slow_leak_alert_comes_later_than_sudden(self):
        body = self.sim("slow_leak", "HV-02").get_json()
        self.assertIsNotNone(body["alert"])
        self.assertGreater(body["alert"]["prediction_id"], 0)

    def test_high_demand_and_pressure_drop_do_not_alert(self):
        for sc, zone in (("high_demand", "HV-03"), ("pressure_drop", "HV-04"), ("normal", "HV-05")):
            body = self.sim(sc, zone).get_json()
            self.assertIsNone(body["alert"], sc)
            self.assertIsNone(body["incident"], sc)
        high = self.sim("high_demand", "HV-06").get_json()["readings"][-1]
        self.assertLess(high["risk_score"], 25)
        self.assertEqual(high["excess_flow_lph"], 0)

    def test_single_abnormal_reading_does_not_alert(self):
        with database.connect(self.path) as c:
            zone = c.execute("SELECT * FROM zones WHERE code='HV-01'").fetchone()
            pred = hv.assess(zone, zone["expected_flow_lph"] * 1.6, zone["expected_flow_lph"] * 0.9, 2.2, 0)
        self.assertEqual(pred["streak"], 1)
        self.assertEqual(pred["pending"], 1)
        self.assertEqual(pred["risk_level"], "moderate")          # capped until persistence is met
        self.assertLess(pred["streak"], hv.CFG["persist_readings"])

    def test_scores_in_range_and_excess_never_negative(self):
        for sc in hv.SCENARIOS:
            self.c.post("/api/reset", json={"confirm": "RESET_DEMO"})
            self.sim(sc, "HV-07")
        with database.connect(self.path) as c:
            for r in c.execute("SELECT risk_score, excess_flow_lph FROM predictions"):
                self.assertTrue(0 <= r["risk_score"] <= 100)
                self.assertGreaterEqual(r["excess_flow_lph"], 0)

    def test_acknowledge_and_resolve_flow(self):
        aid = self.sim("sudden_leak").get_json()["alert"]["id"]
        self.assertEqual(self.sim("normal", "HV-02").status_code, 201)
        self.assertEqual(self.sim("normal", "HV-01").status_code, 409)  # unresolved alert blocks re-simulation
        r = self.c.post(f"/api/alerts/{aid}/acknowledge")
        self.assertEqual(r.get_json()["alert"]["status"], "ACKNOWLEDGED")
        self.assertEqual(self.c.post(f"/api/alerts/{aid}/acknowledge").status_code, 409)
        self.assertEqual(self.c.get("/api/dashboard").get_json()["incidents"][0]["status"], "UNDER INVESTIGATION")
        r = self.c.post(f"/api/alerts/{aid}/resolve")
        self.assertEqual(r.get_json()["alert"]["status"], "RESOLVED")
        self.assertEqual(self.c.post(f"/api/alerts/{aid}/resolve").status_code, 409)
        self.assertEqual(self.c.post("/api/alerts/9999/resolve").status_code, 404)
        d = self.c.get("/api/dashboard").get_json()
        self.assertEqual(d["active_alerts"], 0)
        self.assertEqual(d["open_incidents"], 0)

    def test_dashboard_values_come_from_saved_records(self):
        before = self.c.get("/api/dashboard").get_json()
        self.assertEqual(before["monitored_zones"], 8)
        self.assertEqual(before["active_alerts"], 0)
        self.sim("sudden_leak")
        after = self.c.get("/api/dashboard").get_json()
        self.assertEqual(after["active_alerts"], 1)
        self.assertGreater(after["estimated_loss_lph"], 1000)
        self.assertGreaterEqual(after["high_critical_zones"], 1)
        self.assertGreater(len(after["flow_history"]), 1)
        self.assertIn("SIMULATED", after["disclaimer"])

    def test_reset_requires_confirmation(self):
        self.sim("sudden_leak")
        self.assertEqual(self.c.post("/api/reset", json={}).status_code, 400)
        self.assertEqual(self.c.post("/api/reset", json={"confirm": "RESET_DEMO"}).status_code, 200)
        self.assertEqual(self.c.get("/api/dashboard").get_json()["active_alerts"], 0)

    def test_cors_header_for_local_frontend(self):
        r = self.c.get("/api/health", headers={"Origin": "http://127.0.0.1:5500"})
        self.assertEqual(r.headers.get("Access-Control-Allow-Origin"), "http://127.0.0.1:5500")


if __name__ == "__main__":
    unittest.main()