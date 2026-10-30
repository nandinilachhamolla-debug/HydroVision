/* HydroVision demo - all data is SIMULATED. Rules below are transparent JavaScript, not the trained ML model. */
(function () {
  'use strict';
  // ---- Configurable alert persistence rules ----
  const CFG = { abnormalRaw: 35, alertScore: 50, persistReadings: 3, ticksPerScenario: 6 };
  const KEY = 'hydrovision-demo-v1';
  // name, lat, lng, expected flow (L/h), normal pressure (bar)
  const ZONES = [
    ['Gachibowli', 17.4401, 78.3489, 6200, 3.2], ['Financial District', 17.4172, 78.3433, 7400, 3.4],
    ['Kokapet', 17.393, 78.327, 4800, 3.0], ['Miyapur', 17.4969, 78.3548, 5600, 3.1],
    ['Kukatpally', 17.4948, 78.3996, 8200, 3.3], ['Kondapur', 17.46, 78.365, 6000, 3.2],
    ['Manikonda', 17.405, 78.379, 5200, 3.0], ['Tellapur', 17.463, 78.283, 3900, 2.9]];
  const LEVELS = [['low', 25], ['moderate', 50], ['high', 75], ['critical', 101]];
  const COLORS = { low: '#1e9e55', moderate: '#c99a00', high: '#e8740c', critical: '#d93025' };
  const $ = (s) => document.querySelector(s), $$ = (s) => Array.from(document.querySelectorAll(s));
  const clamp = (x) => Math.max(0, Math.min(1, x));
  const noise = (a) => 1 + (Math.random() * 2 - 1) * a;
  const levelOf = (s) => LEVELS.find((l) => s < l[1])[0];
  const fmt = (n) => Math.round(n).toLocaleString('en-IN');
  let S, map, markers = [], flowChart, riskChart;

  function newZone(i) {
    const z = ZONES[i];
    const o = { id: 'HV-' + String(i + 1).padStart(2, '0'), name: z[0], lat: z[1], lng: z[2], exp: z[3], p0: z[4], streak: 0 };
    reading(o, { f: 1, c: 0.9, p: 0 }); assess(o); return o;
  }
  function fresh() { return { zones: ZONES.map((_, i) => newZone(i)), alerts: [], incidents: [], log: ['Demo started with 8 simulated zones.'], hist: [], clock: 8, n: 1 }; }
  function reading(z, m) {   // multipliers relative to expected flow / expected consumption
    z.flow = z.exp * m.f * noise(0.02); z.cons = z.exp * m.c * noise(0.02); z.pressure = z.p0 + m.p + (Math.random() - 0.5) * 0.08;
    z.time = clockStr();
  }
  const clockStr = () => (S ? String(S.clock % 24).padStart(2, '0') : '08') + ':00';

  // ---- Transparent risk rules ----
  function assess(z) {
    const consExp = z.exp * 0.9, fd = (z.flow - z.exp) / z.exp, cd = (z.cons - consExp) / consExp;
    const expl = fd > 0.05 ? clamp(cd / fd) : 0;                 // share of flow rise explained by consumption
    const cF = clamp((fd - 0.1) / 0.5) * (1 - expl) * 35;        // unexplained flow excess
    const cP = clamp((z.p0 - z.pressure) / 1) * 25;              // pressure drop
    const cM = clamp(((z.flow - z.cons) / z.flow - 0.12) / 0.3) * 25; // flow vs consumption mismatch
    z.raw = cF + cP + cM;
    z.streak = z.raw >= CFG.abnormalRaw ? z.streak + 1 : 0;
    const cT = (Math.min(z.streak, CFG.persistReadings) / CFG.persistReadings) * 15; // persistence
    z.score = Math.round(Math.min(100, z.raw + cT));
    z.parts = { cF, cP, cM, cT, expl };
    z.pending = z.score >= CFG.alertScore && z.streak < CFG.persistReadings;
    z.level = z.pending ? 'moderate' : levelOf(z.score);
    const ex = z.flow - z.exp - Math.max(0, z.cons - consExp);
    z.excess = ex > 0.05 * z.exp ? Math.round(ex) : 0;
  }
  function cause(z) {
    const p = z.parts;
    if (p.expl > 0.6 && z.flow > z.exp * 1.2) return 'High demand: the flow rise is matched by metered consumption, so it is not treated as a leak.';
    if (p.cP > 12 && p.cF < 5 && p.cM < 5) return 'Pressure drop without excess flow: possible pump or supply issue. A pressure drop alone is not proof of leakage.';
    if (z.raw >= CFG.abnormalRaw) return 'Flow exceeds metered consumption while pressure falls: consistent with possible pipe leakage. Needs field verification.';
    return 'Readings are within the normal range for this zone.';
  }
  function action(z) {
    if (z.pending) return 'Watching: abnormal readings so far ' + z.streak + '/' + CFG.persistReadings + '. No alert until the pattern persists.';
    if (z.level === 'critical' || z.level === 'high') return 'Dispatch a team to inspect the main pipe near ' + z.name + ' and verify in the field.';
    if (z.level === 'moderate') return 'Keep monitoring and review pressure logs for ' + z.name + '.';
    return 'No action needed.';
  }

  // ---- Simulation ----
  const SCEN = {
    sudden: () => ({ f: 1.55, c: 0.9, p: -0.9 }),
    slow: (t) => ({ f: 1.12 + 0.09 * t, c: 0.9, p: -(0.1 + 0.12 * t) }),
    demand: () => ({ f: 1.5, c: 1.35, p: -0.25 }),
    pressure: () => ({ f: 0.95, c: 0.86, p: -1.2 })
  };
  const NAMES = { sudden: 'Sudden leak', slow: 'Slow leak', demand: 'High demand', pressure: 'Pressure drop' };
  function simulate(sc) {
    const zi = +$('#simZone').value, target = S.zones[zi];
    if (S.alerts.some((a) => a.zone === target.name && a.status !== 'RESOLVED')) { say('Resolve the open alert for ' + target.name + ' first, or pick another zone.'); return; }
    target.streak = 0;
    for (let t = 0; t < CFG.ticksPerScenario; t++) {
      S.clock++;
      S.zones.forEach((z, i) => { reading(z, i === zi ? SCEN[sc](t) : { f: 1, c: 0.9, p: 0 }); assess(z); });
      S.hist.push({ t: clockStr(), flow: S.zones.reduce((a, z) => a + z.flow, 0), exp: S.zones.reduce((a, z) => a + z.exp, 0) });
      if (target.streak >= CFG.persistReadings && target.score >= CFG.alertScore) raise(target);
    }
    S.hist = S.hist.slice(-12);
    log(NAMES[sc] + ' simulated in ' + target.name + ' (' + CFG.ticksPerScenario + ' hourly readings): score ' + target.score + ', ' + target.level + '.');
    say(NAMES[sc] + ' simulated in ' + target.name + '. ' + (S.alerts.some((a) => a.zone === target.name && a.status !== 'RESOLVED') ? 'Alert raised after persistent abnormal readings.' : 'No alert: the persistence rule was not met.'));
    $('#predZone').value = zi; save(); render();
  }
  function raise(z) {
    if (S.alerts.some((a) => a.zone === z.name && a.status !== 'RESOLVED')) return;
    const a = { id: 'AL-' + S.n, zone: z.name, sev: z.level, time: clockStr() + ' (sim)', reason: cause(z), loss: z.excess, status: 'ACTIVE' };
    S.alerts.unshift(a); S.incidents.unshift({ id: 'INC-' + S.n, alert: a.id, zone: z.name, sev: z.level, opened: a.time, status: 'OPEN' });
    S.n++; log('ALERT ' + a.id + ' (' + a.sev + ') in ' + z.name + '; incident opened.');
  }
  function alertAction(id, act) {
    const a = S.alerts.find((x) => x.id === id), inc = S.incidents.find((x) => x.alert === id);
    if (!a || a.status === 'RESOLVED') return;
    if (act === 'ack' && a.status === 'ACTIVE') { a.status = 'ACKNOWLEDGED'; inc.status = 'UNDER INVESTIGATION'; log(a.id + ' acknowledged.'); }
    if (act === 'res') {
      a.status = 'RESOLVED'; inc.status = 'RESOLVED'; log(a.id + ' resolved; ' + a.zone + ' readings reset to normal (demo).');
      const z = S.zones.find((q) => q.name === a.zone); z.streak = 0; reading(z, { f: 1, c: 0.9, p: 0 }); assess(z);
    }
    save(); render();
  }

  // ---- Rendering ----
  const pill = (l, t) => '<span class="pill ' + l + '">' + (t || l.toUpperCase()) + '</span>';
  const active = () => S.alerts.filter((a) => a.status !== 'RESOLVED');
  function render() {
    const z = S.zones, act = active();
    $('#updated').textContent = clockStr() + ' (sim) / ' + new Date().toLocaleTimeString();
    $('#bellCount').textContent = act.length;
    $('#stZones').textContent = z.length;
    $('#stFlow').textContent = fmt(z.reduce((a, q) => a + q.flow, 0)) + ' L/h';
    $('#stLoss').textContent = fmt(z.reduce((a, q) => a + q.excess, 0)) + ' L/h';
    $('#stHigh').textContent = z.filter((q) => q.level === 'high' || q.level === 'critical').length;
    $('#stAlerts').textContent = act.length;
    $('#stInc').textContent = S.incidents.filter((i) => i.status !== 'RESOLVED').length;
    $('#riskSummary').innerHTML = ['low', 'moderate', 'high', 'critical'].map((l) => {
      const n = z.filter((q) => q.level === l).length;
      return '<div class="bar">' + pill(l) + '<i style="width:' + n * 28 + 'px;background:' + COLORS[l] + '"></i> ' + n + '</div>';
    }).join('') + '<p class="muted">Estimated potential loss assumes the current excess flow persists; it is not measured leakage.</p>';
    $('#recentAlerts').innerHTML = S.alerts.slice(0, 3).map(alertHtml).join('') || '<p class="muted">No alerts. Run a simulation to see one.</p>';
    $('#activity').innerHTML = S.log.slice(0, 12).map((l) => '<li>' + l + '</li>').join('');
    renderTable(); renderMap(); renderPred();
    $('#alertList').innerHTML = S.alerts.map(alertHtml).join('') || '<p class="notice">No alerts yet. Use the simulation buttons above.</p>';
    $('#incList').innerHTML = S.incidents.map((i) => '<div class="item ' + i.sev + (i.status === 'RESOLVED' ? ' RESOLVED' : '') + '"><b>' + i.id + '</b> ' + pill(i.sev) + ' ' + i.zone +
      '<br>Status: <b>' + i.status + '</b> | Opened: ' + i.opened + ' | Linked alert: ' + i.alert + '</div>').join('') || '<p class="notice">No incidents. An incident opens automatically when an alert is raised.</p>';
    renderCons(); renderCharts();
  }
  function alertHtml(a) {
    const done = a.status === 'RESOLVED';
    return '<div class="item ' + a.sev + (done ? ' RESOLVED' : '') + '"><b>' + a.id + '</b> ' + pill(a.sev) + ' ' + a.zone + ' | ' + a.time + ' | <b>' + a.status + '</b><br>' + a.reason +
      '<br>Estimated potential loss: ' + fmt(a.loss) + ' L/h (' + fmt(a.loss * 24) + ' L/day if it persisted)<br>' +
      '<button class="act" data-act="ack" data-id="' + a.id + '"' + (a.status !== 'ACTIVE' ? ' disabled' : '') + '>Acknowledge</button>' +
      '<button class="act" data-act="res" data-id="' + a.id + '"' + (done ? ' disabled' : '') + '>Resolve</button></div>';
  }
  function renderTable() {
    const q = $('#search').value.trim().toLowerCase(), f = $('#filter').value;
    const rows = S.zones.filter((z) => (f === 'all' || z.level === f) && z.name.toLowerCase().includes(q));
    $('#monBody').innerHTML = rows.map((z) => '<tr><td>' + z.name + '</td><td>' + fmt(z.flow) + '</td><td>' + fmt(z.exp) + '</td><td>' + z.pressure.toFixed(2) + '</td><td>' + fmt(z.cons) +
      '</td><td>' + z.score + '</td><td>' + pill(z.level) + (z.pending ? ' <small>unconfirmed</small>' : '') + '</td><td>' + z.time + '</td></tr>').join('') ||
      '<tr><td colspan="8">No zones match the search/filter.</td></tr>';
  }
  function popup(z) {
    return '<b>' + z.name + '</b> (SIMULATED)<br>Flow: ' + fmt(z.flow) + ' L/h<br>Pressure: ' + z.pressure.toFixed(2) + ' bar<br>Risk score: ' + z.score + ' (heuristic)<br>Status: ' + z.level.toUpperCase() + (z.pending ? ' (unconfirmed)' : '');
  }
  function initMap() {
    if (typeof L === 'undefined') { $('#mapFallback').hidden = false; $('#mapBox').hidden = true; return; }
    try {
      map = L.map('mapBox').setView([17.445, 78.36], 11);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors', maxZoom: 18 }).addTo(map);
      markers = S.zones.map((z) => L.circleMarker([z.lat, z.lng], { radius: 11, weight: 2, fillOpacity: 0.85 }).addTo(map).bindPopup(popup(z)));
    } catch (e) { map = null; $('#mapFallback').hidden = false; $('#mapBox').hidden = true; }
  }
  function renderMap() {
    if (!map) return;
    S.zones.forEach((z, i) => { markers[i].setStyle({ color: '#fff', fillColor: COLORS[z.level] }); markers[i].setPopupContent(popup(z)); });
  }
  function renderPred() {
    const z = S.zones[+$('#predZone').value || 0], p = z.parts;
    $('#predBox').innerHTML = '<h3>' + z.name + ' (simulated) ' + pill(z.level) + '</h3>' +
      '<p><b>Risk score:</b> ' + z.score + ' / 100 <span class="muted">(heuristic indicator, not a probability of leakage)</span></p>' +
      '<p><b>Anomaly score:</b> ' + (z.raw / 100).toFixed(2) + ' <span class="muted">(rule-based 0-1 index from the same rules)</span></p>' +
      '<p><b>Possible cause:</b> ' + cause(z) + '</p><p><b>Estimated excess flow:</b> ' + fmt(z.excess) + ' L/h (estimate)</p><p><b>Recommended next action:</b> ' + action(z) + '</p>' +
      '<p class="muted">Score parts: unexplained flow ' + p.cF.toFixed(0) + '/35, pressure drop ' + p.cP.toFixed(0) + '/25, flow-vs-consumption mismatch ' + p.cM.toFixed(0) + '/25, persistence ' + p.cT.toFixed(0) + '/15.</p>';
  }
  function renderCons() {
    const need = S.zones.filter((z) => z.score >= 25 || z.pending).map((z) => '<div class="item ' + z.level + '"><b>' + z.name + '</b> ' + pill(z.level) + '<br>' + action(z) + '<br><span class="muted">' + cause(z) + '</span></div>');
    $('#consList').innerHTML = (need.join('') || '<p class="notice">All simulated zones are normal. Run a simulation to see zone-specific recommendations.</p>') +
      '<div class="card"><h3>General good practice</h3><ul><li>Inspect zones with persistent night-time flow.</li><li>Review pressure management in low-demand hours where operationally appropriate.</li><li>Verify every model-based alert in the field before repair decisions.</li></ul></div>';
  }
  function renderCharts() {
    if (typeof Chart === 'undefined') { $$('.chartbox').forEach((b) => { b.innerHTML = '<p class="notice">Charts unavailable (Chart.js could not load). Check your internet connection.</p>'; }); return; }
    if (!flowChart) {
      flowChart = new Chart($('#flowChart'), { type: 'line', data: { labels: [], datasets: [{ label: 'Observed flow (L/h)', data: [], borderColor: '#1f6feb', tension: 0.3 }, { label: 'Expected flow (L/h)', data: [], borderColor: '#0f9d9a', borderDash: [6, 4], tension: 0.3 }] }, options: { maintainAspectRatio: false, animation: false } });
      riskChart = new Chart($('#riskChart'), { type: 'bar', data: { labels: [], datasets: [{ label: 'Risk score (heuristic)', data: [], backgroundColor: [] }] }, options: { maintainAspectRatio: false, animation: false, scales: { y: { min: 0, max: 100 } } } });
    }
    const h = S.hist.length ? S.hist : [{ t: clockStr(), flow: S.zones.reduce((a, z) => a + z.flow, 0), exp: S.zones.reduce((a, z) => a + z.exp, 0) }];
    flowChart.data.labels = h.map((x) => x.t); flowChart.data.datasets[0].data = h.map((x) => Math.round(x.flow)); flowChart.data.datasets[1].data = h.map((x) => Math.round(x.exp)); flowChart.update();
    riskChart.data.labels = S.zones.map((z) => z.name); riskChart.data.datasets[0].data = S.zones.map((z) => z.score); riskChart.data.datasets[0].backgroundColor = S.zones.map((z) => COLORS[z.level]); riskChart.update();
  }

  // ---- State, events ----
  function log(m) { S.log.unshift(clockStr() + ' (sim) ' + m); S.log = S.log.slice(0, 40); }
  function say(m) { $('#simMsg').textContent = m; }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) { /* storage unavailable: demo still works */ } }
  function load() {
    try { const s = JSON.parse(localStorage.getItem(KEY)); if (s && Array.isArray(s.zones) && s.zones.length === ZONES.length && s.zones[0].parts) return s; } catch (e) { /* ignore */ }
    return null;
  }
  function show(id) {
    $$('.sec').forEach((s) => s.classList.toggle('active', s.id === id));
    $$('nav button').forEach((b) => b.classList.toggle('active', b.dataset.sec === id));
    if (id === 'map' && map) setTimeout(() => map.invalidateSize(), 50);
    window.scrollTo(0, 0);
  }
  function init() {
    S = load() || fresh();
    const opts = S.zones.map((z, i) => '<option value="' + i + '">' + z.name + '</option>').join('');
    $('#simZone').innerHTML = opts; $('#predZone').innerHTML = opts;
    initMap();
    document.addEventListener('click', (e) => {
      const t = e.target.closest('button'); if (!t) return;
      if (t.dataset.sec) show(t.dataset.sec);
      else if (t.id === 'bell') show('alerts');
      else if (t.dataset.sc === 'reset') { S = fresh(); save(); say('Demo reset to normal operation.'); render(); }
      else if (t.dataset.sc) simulate(t.dataset.sc);
      else if (t.dataset.act) alertAction(t.dataset.id, t.dataset.act);
    });
    $('#search').addEventListener('input', renderTable); $('#filter').addEventListener('change', renderTable); $('#predZone').addEventListener('change', renderPred);
    render();
  }
  document.addEventListener('DOMContentLoaded', init);
})();