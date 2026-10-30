"""HydroVision Flask backend (prototype). ALL DATA IS SIMULATED.

- Risk score = transparent demo rules (a heuristic 0-100 index, NOT a calibrated probability).
- The trained Stage A ML model is NOT connected to this backend.
- Alerts need persistence: several consecutive abnormal readings (see CFG).
Run:  python app.py      (from the backend folder)   then open http://127.0.0.1:5000
"""
import random
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory

import database

app = Flask(__name__)
app.config["DB_PATH"] = database.DEFAULT_DB_PATH

# Allow the frontend (Live Server etc.) to call the API from another local port.
ORIGINS = ["http://127.0.0.1:5500", "http://localhost:5500", "http://127.0.0.1:5000", "http://localhost:5000",
           "http://127.0.0.1:8000", "http://localhost:8000", "http://localhost:3000", "http://localhost:5173"]
try:
    from flask_cors import CORS
    CORS(app, resources={r"/api/*": {"origins": ORIGINS}})
except ImportError:                       # fallback so the demo still works if Flask-CORS is not installed
    print("WARNING: flask-cors not installed; using a minimal built-in CORS header. Run: pip install -r requirements.txt")

    @app.after_request
    def _cors(resp):
        if request.headers.get("Origin") in ORIGINS:
            resp.headers["Access-Control-Allow-Origin"] = request.headers["Origin"]
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp

# ---- Configurable alert persistence rules ----
# noise_floor: excess flow below this fraction of expected flow is treated as sensor noise and reported as 0
CFG = {"abnormal_raw": 35, "alert_score": 50, "persist_readings": 3, "ticks_per_scenario": 6, "noise_floor": 0.08}
SCENARIOS = {  # multipliers of expected flow / expected consumption, pressure change (bar) per hourly reading
    "normal": lambda t: (1.0, 0.9, 0.0),
    "sudden_leak": lambda t: (1.55, 0.9, -0.9),
    "slow_leak": lambda t: (1.12 + 0.09 * t, 0.9, -(0.1 + 0.12 * t)),
    # water balance: flow = consumption + normal background loss (0.10), so 1.35 + 0.10 = 1.45 (a demand rise, NOT a leak)
    "high_demand": lambda t: (1.45, 1.35, -0.25),
    "pressure_drop": lambda t: (0.95, 0.86, -1.2),
}
LEVELS = [("low", 25), ("moderate", 50), ("high", 75), ("critical", 101)]
DISCLAIMER = ("SIMULATED data. risk_score is a heuristic demo index, not a calibrated probability of leakage. "
              "Excess flow is an estimate. The trained ML model is not connected.")


def db():
    return database.connect(app.config["DB_PATH"])


def clamp(x):
    return max(0.0, min(1.0, x))


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def row(r):
    return dict(r) if r is not None else None


# ---------------------------------------------------------------- scoring (same rules as the website's fallback demo)
def assess(zone, flow, cons, pressure, prev_streak):
    exp, p0 = zone["expected_flow_lph"], zone["normal_pressure_bar"]
    cons_exp = exp * 0.9
    fd, cd = (flow - exp) / exp, (cons - cons_exp) / cons_exp
    expl = clamp(cd / fd) if fd > 0.05 else 0.0                 # share of the flow rise explained by consumption
    c_flow = clamp((fd - 0.1) / 0.5) * (1 - expl) * 35          # unexplained flow excess
    c_press = clamp((p0 - pressure) / 1.0) * 25                 # pressure drop
    c_mis = clamp(((flow - cons) / flow - 0.12) / 0.3) * 25     # flow vs consumption mismatch
    raw = c_flow + c_press + c_mis
    streak = prev_streak + 1 if raw >= CFG["abnormal_raw"] else 0
    n = CFG["persist_readings"]
    c_pers = min(streak, n) / n * 15                            # persistence
    score = int(round(min(100.0, raw + c_pers)))
    pending = score >= CFG["alert_score"] and streak < n
    level = "moderate" if pending else next(k for k, lim in LEVELS if score < lim)
    excess = flow - exp - max(0.0, cons - cons_exp)
    excess = round(excess) if excess > CFG["noise_floor"] * exp else 0   # below the noise floor, and never negative
    if expl > 0.6 and flow > exp * 1.2:
        cause = "High demand: the flow rise is matched by metered consumption, so it is not treated as a leak."
    elif c_press > 12 and c_flow < 5 and c_mis < 5:
        cause = "Pressure drop without excess flow: possible pump or supply issue. A pressure drop alone is not proof of leakage."
    elif raw >= CFG["abnormal_raw"]:
        cause = "Flow exceeds metered consumption while pressure falls: consistent with possible pipe leakage. Needs field verification."
    else:
        cause = "Readings are within the normal range for this zone."
    if pending:
        action = f"Watching: abnormal readings so far {streak}/{n}. No alert until the pattern persists."
    elif level in ("high", "critical"):
        action = f"Dispatch a team to inspect the main pipe near {zone['name']} and verify in the field."
    elif level == "moderate":
        action = f"Keep monitoring and review pressure logs for {zone['name']}."
    else:
        action = "No action needed."
    return dict(raw_score=round(raw, 2), risk_score=score, risk_level=level, streak=streak, pending=int(pending),
                comp_flow=round(c_flow, 2), comp_pressure=round(c_press, 2), comp_mismatch=round(c_mis, 2),
                comp_persistence=round(c_pers, 2), demand_explained=round(expl, 3), excess_flow_lph=excess,
                cause=cause, action=action)


def save_reading(conn, zone, scenario, mult, sim_hour):
    """Generate one simulated reading, run the rules, save reading + prediction. Returns (reading_id, prediction_id, pred)."""
    f, c, p = mult
    flow = zone["expected_flow_lph"] * f * random.uniform(0.98, 1.02)
    cons = zone["expected_flow_lph"] * c * random.uniform(0.98, 1.02)
    pressure = zone["normal_pressure_bar"] + p + random.uniform(-0.04, 0.04)
    prev = conn.execute("SELECT p.streak FROM predictions p JOIN sensor_readings r ON r.id = p.reading_id "
                        "WHERE r.zone_id = ? ORDER BY r.id DESC LIMIT 1", (zone["id"],)).fetchone()
    pred = assess(zone, flow, cons, pressure, prev["streak"] if prev else 0)
    rid = conn.execute("INSERT INTO sensor_readings (zone_id, sim_hour, time_label, recorded_at, flow_lph, pressure_bar, "
                       "consumption_lph, scenario) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (zone["id"], sim_hour, f"{sim_hour % 24:02d}:00", now(), round(flow, 1), round(pressure, 3),
                        round(cons, 1), scenario)).lastrowid
    cols = list(pred)
    pid = conn.execute(f"INSERT INTO predictions (reading_id, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))})",
                       [rid] + [pred[k] for k in cols]).lastrowid
    return rid, pid, pred


def current_hour(conn):
    return conn.execute("SELECT COALESCE(MAX(sim_hour), 7) FROM sensor_readings").fetchone()[0]


def seed_initial_readings():
    """First start only: one normal reading per zone so the dashboard is not empty."""
    with db() as conn:
        if conn.execute("SELECT COUNT(*) FROM sensor_readings").fetchone()[0] == 0:
            for z in conn.execute("SELECT * FROM zones ORDER BY id").fetchall():
                save_reading(conn, z, "normal", SCENARIOS["normal"](0), 8)


def startup():
    database.init_db(app.config["DB_PATH"])
    seed_initial_readings()
startup()


LATEST_SQL = ("SELECT z.id AS zone_pk, r.id AS reading_id, r.time_label AS time, r.flow_lph, r.pressure_bar, r.consumption_lph, "
              "r.scenario, p.raw_score, p.risk_score, p.risk_level, p.streak, p.pending, p.comp_flow, p.comp_pressure, "
              "p.comp_mismatch, p.comp_persistence, p.demand_explained, p.excess_flow_lph, p.cause, p.action "
              "FROM zones z JOIN sensor_readings r ON r.id = (SELECT MAX(id) FROM sensor_readings WHERE zone_id = z.id) "
              "JOIN predictions p ON p.reading_id = r.id")


def alert_json(r):
    d = dict(r)
    d["code"] = f"AL-{d['id']}"
    return d


# ---------------------------------------------------------------- routes
@app.get("/api/health")
def health():
    try:
        with db() as conn:
            counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                      for t in ("zones", "sensor_readings", "predictions", "alerts", "incidents")}
        return jsonify(status="ok", database="ok", counts=counts, data_source="SIMULATED", model_connected=False)
    except Exception as exc:
        return jsonify(status="error", database="unavailable", message=str(exc)), 503


@app.get("/api/zones")
def zones():
    with db() as conn:
        latest = {r["zone_pk"]: dict(r) for r in conn.execute(LATEST_SQL).fetchall()}
        out = []
        for z in conn.execute("SELECT * FROM zones ORDER BY id").fetchall():
            d = dict(z)
            d["latest"] = latest.get(z["id"])
            out.append(d)
    return jsonify(zones=out, data_source="SIMULATED")


@app.get("/api/readings")
def readings():
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        return jsonify(error="limit must be an integer"), 400
    if not 1 <= limit <= 500:
        return jsonify(error="limit must be between 1 and 500"), 400
    sql = ("SELECT r.id, z.code AS zone_id, z.name AS zone_name, r.sim_hour, r.time_label, r.recorded_at, r.flow_lph, "
           "r.pressure_bar, r.consumption_lph, r.scenario, r.data_source, p.risk_score, p.risk_level, p.excess_flow_lph "
           "FROM sensor_readings r JOIN zones z ON z.id = r.zone_id JOIN predictions p ON p.reading_id = r.id ")
    args = []
    if request.args.get("zone_id"):
        sql += "WHERE z.code = ? "
        args.append(request.args["zone_id"].strip().upper())
    with db() as conn:
        rows = conn.execute(sql + "ORDER BY r.id DESC LIMIT ?", args + [limit]).fetchall()
    return jsonify(readings=[dict(r) for r in rows], data_source="SIMULATED")


@app.get("/api/alerts")
def alerts():
    status = request.args.get("status")
    if status and status.upper() not in ("ACTIVE", "ACKNOWLEDGED", "RESOLVED"):
        return jsonify(error="status must be ACTIVE, ACKNOWLEDGED or RESOLVED"), 400
    sql = ("SELECT a.*, z.code AS zone_code, z.name AS zone_name FROM alerts a JOIN zones z ON z.id = a.zone_id ")
    args = []
    if status:
        sql += "WHERE a.status = ? "
        args.append(status.upper())
    with db() as conn:
        rows = conn.execute(sql + "ORDER BY a.id DESC", args).fetchall()
    return jsonify(alerts=[alert_json(r) for r in rows], data_source="SIMULATED")


@app.get("/api/dashboard")
def dashboard():
    with db() as conn:
        latest = conn.execute(LATEST_SQL).fetchall()
        history = conn.execute("SELECT r.sim_hour, MAX(r.time_label) AS t, SUM(r.flow_lph) AS flow, SUM(z.expected_flow_lph) AS expected "
                               "FROM sensor_readings r JOIN zones z ON z.id = r.zone_id GROUP BY r.sim_hour "
                               "ORDER BY r.sim_hour DESC LIMIT 12").fetchall()
        incidents = conn.execute("SELECT i.*, z.name AS zone_name FROM incidents i JOIN zones z ON z.id = i.zone_id ORDER BY i.id DESC").fetchall()
        active = conn.execute("SELECT COUNT(*) FROM alerts WHERE status != 'RESOLVED'").fetchone()[0]
        hour = current_hour(conn)
    counts = {k: sum(1 for r in latest if r["risk_level"] == k) for k, _ in LEVELS}
    return jsonify(
        monitored_zones=len(latest), current_flow_lph=round(sum(r["flow_lph"] for r in latest)),
        estimated_loss_lph=round(sum(r["excess_flow_lph"] for r in latest)),
        high_critical_zones=counts["high"] + counts["critical"], active_alerts=active,
        open_incidents=sum(1 for i in incidents if i["status"] != "RESOLVED"), risk_counts=counts, sim_hour=hour,
        flow_history=[dict(h) for h in reversed(history)],
        incidents=[dict(i, code=f"INC-{i['id']}", alert_code=f"AL-{i['alert_id']}") for i in incidents],
        data_source="SIMULATED", disclaimer=DISCLAIMER)


@app.post("/api/simulation")
def simulation():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Request body must be a JSON object, e.g. {\"scenario\": \"sudden_leak\", \"zone_id\": \"HV-01\"}"), 400
    scenario, code = body.get("scenario"), body.get("zone_id")
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        return jsonify(error=f"Invalid scenario. Allowed: {sorted(SCENARIOS)}"), 400
    if not isinstance(code, str) or not code.strip():
        return jsonify(error="zone_id is required (for example \"HV-01\")"), 400
    with db() as conn:
        zone = conn.execute("SELECT * FROM zones WHERE code = ?", (code.strip().upper(),)).fetchone()
        if zone is None:
            return jsonify(error=f"Zone '{code}' not found"), 404
        if conn.execute("SELECT 1 FROM alerts WHERE zone_id = ? AND status != 'RESOLVED'", (zone["id"],)).fetchone():
            return jsonify(error=f"{zone['name']} has an unresolved alert. Resolve it first or choose another zone."), 409
        hour, saved, alert, incident = current_hour(conn), [], None, None
        for t in range(CFG["ticks_per_scenario"]):
            hour += 1
            for z in conn.execute("SELECT * FROM zones ORDER BY id").fetchall():     # other zones keep running normally
                is_target = z["id"] == zone["id"]
                rid, pid, pred = save_reading(conn, z, scenario if is_target else "normal",
                                              SCENARIOS[scenario](t) if is_target else SCENARIOS["normal"](0), hour)
                if not is_target:
                    continue
                saved.append(rid)
                if pred["streak"] >= CFG["persist_readings"] and pred["risk_score"] >= CFG["alert_score"] and alert is None:
                    aid = conn.execute("INSERT INTO alerts (zone_id, prediction_id, severity, reason, est_loss_lph, time_label, created_at) "
                                       "VALUES (?, ?, ?, ?, ?, ?, ?)", (zone["id"], pid, pred["risk_level"], pred["cause"],
                                                                        pred["excess_flow_lph"], f"{hour % 24:02d}:00 (sim)", now())).lastrowid
                    iid = conn.execute("INSERT INTO incidents (alert_id, zone_id, severity, time_label, opened_at) VALUES (?, ?, ?, ?, ?)",
                                       (aid, zone["id"], pred["risk_level"], f"{hour % 24:02d}:00 (sim)", now())).lastrowid
                    alert = row(conn.execute("SELECT * FROM alerts WHERE id = ?", (aid,)).fetchone())
                    incident = row(conn.execute("SELECT * FROM incidents WHERE id = ?", (iid,)).fetchone())
        marks = ",".join("?" * len(saved))
        rows = conn.execute("SELECT r.*, p.* FROM sensor_readings r JOIN predictions p ON p.reading_id = r.id "
                            f"WHERE r.id IN ({marks}) ORDER BY r.id", saved).fetchall()
        last = rows[-1]
    msg = (f"{scenario} simulated in {zone['name']}: final risk score {last['risk_score']} ({last['risk_level']}). "
           + ("Alert raised after persistent abnormal readings." if alert else "No alert: the persistence rule was not met."))
    return jsonify(message=msg, scenario=scenario, zone=zone["name"], readings=[dict(r) for r in rows], alert=alert,
                   incident=incident, data_source="SIMULATED", disclaimer=DISCLAIMER), 201


def alert_transition(alert_id, action):
    with db() as conn:
        a = conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if a is None:
            return jsonify(error=f"Alert {alert_id} not found"), 404
        if action == "ack":
            if a["status"] != "ACTIVE":
                return jsonify(error=f"Only ACTIVE alerts can be acknowledged (this one is {a['status']})"), 409
            conn.execute("UPDATE alerts SET status = 'ACKNOWLEDGED', acknowledged_at = ? WHERE id = ?", (now(), alert_id))
            conn.execute("UPDATE incidents SET status = 'UNDER INVESTIGATION' WHERE alert_id = ?", (alert_id,))
        else:
            if a["status"] == "RESOLVED":
                return jsonify(error="Alert is already resolved"), 409
            conn.execute("UPDATE alerts SET status = 'RESOLVED', resolved_at = ? WHERE id = ?", (now(), alert_id))
            conn.execute("UPDATE incidents SET status = 'RESOLVED', resolved_at = ? WHERE alert_id = ?", (now(), alert_id))
            zone = conn.execute("SELECT * FROM zones WHERE id = ?", (a["zone_id"],)).fetchone()
            save_reading(conn, zone, "normal", SCENARIOS["normal"](0), current_hour(conn) + 1)   # demo: zone returns to normal
        return jsonify(alert=alert_json(conn.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()))


@app.post("/api/alerts/<int:alert_id>/acknowledge")
def acknowledge(alert_id):
    return alert_transition(alert_id, "ack")


@app.post("/api/alerts/<int:alert_id>/resolve")
def resolve(alert_id):
    return alert_transition(alert_id, "res")


@app.post("/api/reset")
def reset():
    """Deletes ALL simulated readings/alerts/incidents. Needs an explicit confirmation in the body."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("confirm") != "RESET_DEMO":
        return jsonify(error="Send {\"confirm\": \"RESET_DEMO\"} to reset the simulated demo data"), 400
    with db() as conn:
        for t in ("incidents", "alerts", "predictions", "sensor_readings"):
            conn.execute(f"DELETE FROM {t}")
    seed_initial_readings()
    return jsonify(message="Demo data reset to normal operation")


# ---------------------------------------------------------------- error handling + optional static hosting
@app.errorhandler(404)
def not_found(_e):
    return jsonify(error="Not found"), 404


@app.errorhandler(405)
def bad_method(_e):
    return jsonify(error="Method not allowed"), 405


@app.errorhandler(Exception)
def server_error(exc):
    if hasattr(exc, "code") and isinstance(exc.code, int):          # normal HTTP errors keep their status
        return jsonify(error=getattr(exc, "description", str(exc))), exc.code
    app.logger.exception("Unhandled error")
    return jsonify(error="Internal server error", detail=str(exc)), 500


@app.get("/")
def index():
    return send_from_directory(database.PROJECT_DIR, "index.html")


@app.get("/<name>")
def static_file(name):
    if name in ("style.css", "script.js"):
        return send_from_directory(database.PROJECT_DIR, name)
    return jsonify(error="Not found"), 404


# Initialize the database when the app starts,
# including when Render starts it using Gunicorn.
startup()

if __name__ == "__main__":
    print("HydroVision backend (SIMULATED data) on http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
    startup()
    print("HydroVision backend (SIMULATED data) on http://127.0.0.1:5000  - database:", app.config["DB_PATH"])
    app.run(host="127.0.0.1", port=5000, debug=False)