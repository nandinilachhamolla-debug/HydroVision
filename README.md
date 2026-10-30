# HydroVision - Demo Website (DEMO DATA)

AI-Based Urban Water Leakage Detection & Smart Conservation System. *See the Leak. Save the Water.*
Plain HTML/CSS/JavaScript. All readings are **simulated**; this is not real municipal data.

## Run it (VS Code, Windows)
1. Put `index.html`, `style.css`, `script.js`, `README.md` in one folder (e.g. `C:\Projects\hydrovision-website`).
2. VS Code: **File > Open Folder** and choose that folder.
3. Install the **Live Server** extension (Ritwick Dey): Extensions icon, search "Live Server", Install.
4. Right-click `index.html` > **Open with Live Server**. The site opens at `http://127.0.0.1:5500`.
   (Double-clicking `index.html` also works, but the map tiles can fail from `file://`. Use Live Server.)
   Alternative: in a terminal run `python -m http.server 8000` and open `http://localhost:8000`.
An internet connection is needed for the map and chart libraries (CDN).

## Test every button
Top bar (works on any page). Pick a zone in the dropdown first.
- **Simulate Sudden Leak:** 6 hourly readings with high flow, unchanged consumption, big pressure drop. Alert + incident appear (after 3 persistent readings). Check Overview cards, Live Monitoring, Risk Map (marker turns red/orange), Alerts, Incidents.
- **Simulate Slow Leak:** gradual rise; the alert appears later in the 6 readings.
- **Simulate High Demand:** flow AND consumption rise together. No alert, no leak label (status stays low).
- **Simulate Pressure Drop:** pressure falls with no excess flow. Moderate only, no alert; explained as "not proof of leakage".
- **Reset Demo:** returns everything to normal and clears alerts/incidents.
- **Acknowledge / Resolve** (Alerts page): alert and incident status change together; Resolve resets that zone.
- Also try: sidebar items, bell icon (opens Alerts), table search and risk filter, zone selector in AI Predictions, map markers.
A zone with an unresolved alert cannot be simulated again until you resolve it.

## Alert persistence rules (editable in `script.js`, `CFG`)
- `abnormalRaw: 35` - a reading counts as abnormal when its raw rule score is at least 35.
- `persistReadings: 3` - an alert needs 3 consecutive abnormal readings and `alertScore: 50` (final score).
- A single spike therefore shows as "unconfirmed" (capped at Moderate) and creates no alert.

## Troubleshooting
- **Blank map or charts:** no internet or CDN blocked; a message is shown instead. Reload when online.
- **Changes not showing:** hard refresh (Ctrl+Shift+R).
- **Odd old state:** press Reset Demo, or clear site data (the demo stores state in localStorage).
- **Nothing happens on click:** open DevTools (F12) > Console and check for errors; make sure all 3 files are in the same folder with these exact names.

## Implemented vs simulated
Implemented: navigation, simulation, transparent scoring rules, persistence-based alerts, incidents, estimated excess flow, search/filter, map, charts, localStorage.
Simulated / not implemented: all readings are generated in the browser; the trained ML model, a backend, a database and real sensors/ESP32 are **not** connected. The risk score is a heuristic indicator, not a calibrated probability. Estimated loss is an estimate, not measured leakage or saved water. A rainfall series is not included.