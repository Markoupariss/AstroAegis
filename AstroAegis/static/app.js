'use strict';

/* ---------------------------------------------------------------- state & helpers */
const S = { meta: null, list: [], id: null, data: null, tab: 'overview', hist: null, search: '',
            saveTimer: null, live: null, openRule: null };

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const $ = (sel, root = document) => root.querySelector(sel);
const T = () => S.meta.i18n;
const lvlLabel = l => T().levels[l] || l;
const sigLabel = k => T().signals[k] || k;
const symLabel = k => T().symptoms[k] || S.meta.symptoms_en[k] || k;
const ctxLabel = k => T().context[k] || S.meta.context_en[k] || k;
const condName = id => T().conditions[id] || id;
const fmt = v => (v == null ? '–' : (Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100)));
const initials = n => n.split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase();
const unitOf = k => (S.meta.readings.find(r => r.key === k) || (S.meta.derived[k] || {})).unit || '';
const MAIN_VITALS = ['heart_rate', 'blood_pressure_systolic', 'blood_pressure_diastolic', 'spo2',
                     'skin_temperature', 'cabin_co2', 'qtc_interval'];
const DERIVED_INPUTS = ['core_temperature', 'watery_stool_count_24h', 'systolic_bp_drop_on_standing',
                        'diastolic_bp_drop_on_standing', 'symptom_duration_hours'];
const DERIVED_UNITS = { core_temperature: 'C', watery_stool_count_24h: 'bowel movements', systolic_bp_drop_on_standing: 'mmHg',
                        diastolic_bp_drop_on_standing: 'mmHg', symptom_duration_hours: 'hours' };
const CAT_ORDER = ['cardiovascular', 'respiratory', 'vital', 'environment', 'symptom', 'blood_panel', 'radiation'];

async function api(method, url, body) {
  const r = await fetch('/api' + url, { method, headers: { 'Content-Type': 'application/json' },
                                         body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
}

function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('show'), 4500);
}
const guard = fn => async (...a) => { try { return await fn(...a); } catch (e) { toast(e.message); } };

/* ------------------------------------------------------------------------- gauge */
function statusAt(l, v) {
  if ((l.critical_above != null && v > l.critical_above) || (l.critical_below != null && v < l.critical_below)) return 'critical';
  if ((l.caution_above != null && v > l.caution_above) || (l.caution_below != null && v < l.caution_below)) return 'caution';
  return 'normal';
}
function gauge(sig) {
  const [lo, hi] = sig.scale, l = sig.limits, span = hi - lo || 1;
  const cuts = [...new Set(Object.values(l).filter(v => v != null))].sort((a, b) => a - b);
  const pts = [lo, ...cuts.filter(c => c > lo && c < hi), hi];
  const color = { normal: '#2ecc71', caution: '#ffc233', critical: '#ff3b3b' };
  const stops = [];
  for (let i = 0; i < pts.length - 1; i++) {
    const c = color[statusAt(l, (pts[i] + pts[i + 1]) / 2)];
    stops.push(`${c} ${((pts[i] - lo) / span) * 100}%`, `${c} ${((pts[i + 1] - lo) / span) * 100}%`);
  }
  const pos = Math.max(0, Math.min(100, ((sig.value - lo) / span) * 100));
  return `<div class="gauge" style="background:linear-gradient(90deg,${stops.join(',')})"><i style="left:${pos}%"></i></div>`;
}
function tile(sig, mini = false) {
  return `<div class="tile st-${sig.status} ${mini ? 'mini' : ''}" title="${esc(sig.source || '')}">
    <div class="t-label">${esc(sigLabel(sig.key))}</div>
    <div class="t-val">${fmt(sig.value)}<small>${esc(sig.unit)}</small></div>${gauge(sig)}
    <div class="t-state">${esc(T().signal_status[sig.status])}</div></div>`;
}

/* ------------------------------------------------------------------------ sidebar */
function renderSidebar() {
  $('#sidebar').innerHTML = `
    <div class="brand"><div class="logo"><img src="logo.svg" alt="AstroAegis emblem"></div><div><b>AstroAegis</b><small>Crew health intelligence</small></div></div>
    <div class="side-title">CREW</div>
    ${S.list.map(a => `
      <button class="astro ${a.id === S.id ? 'active' : ''}" data-action="select" data-arg="${esc(a.id)}">
        <div class="avatar" style="background:${esc(a.color)}">${esc(initials(a.name))}</div>
        <div class="meta"><b>${esc(a.name)}</b><small>${esc(a.role || '—')} · Day ${a.mission_day}</small>
          <small>${esc(lvlLabel(a.overall))}${a.environment_alert ? ' · ⚠ Environment' : ''}</small></div>
        <span class="dot lvl-${a.overall}" title="${esc(lvlLabel(a.overall))}"></span>
      </button>`).join('')}
    <button class="add-btn" data-action="newprofile">＋ Add astronaut</button><button class="add-btn" data-action="importprofile">⇧ Import medical JSON</button><button class="add-btn" data-action="importdatabase">⚙ Update rule database</button>`;
}

/* -------------------------------------------------------------------- main layout */
function tabsDef() {
  const n = S.data ? S.data.assessment.findings.length : 0;
  return [['overview', 'Overview'], ['sensors', 'Sensors'], ['symptoms', 'Symptoms'],
          ['dx', 'Assessment & Actions' + (n ? `<span class="badge">${n}</span>` : '')],
          ['sim', 'Simulation'], ['hist', 'History'], ['predict', 'Forecast']];
}
function renderMain() {
  const d = S.data;
  if (!d) { $('#main').innerHTML = '<div class="empty">No astronaut profiles yet. Add one to get started.</div>'; return; }
  const p = d.profile;
  $('#main').innerHTML = `
    <div class="head" id="head"></div>
    <div class="tabs" id="tabs"></div>
    <div id="content"></div>`;
  renderHead(); renderTabs(); renderTab();
  void p;
}
function renderHead() {
  const d = S.data, p = d.profile, o = d.assessment.overall;
  $('#head').innerHTML = `
    <div class="avatar" style="background:${esc(d.color)}">${esc(initials(p.name))}</div>
    <div><h1>${esc(p.name)}</h1>
      <div class="sub">ID: ${esc(S.id || p.astronaut_id || '—')} · ${esc(p.role || '—')} · ${p.sex === 'female' ? 'Female' : 'Male'}, ${p.age} years ·
      Mission day ${p.mission_day}/${p.mission_duration_days}</div></div>
    <div class="spacer"></div>
    <span class="pill lvl-${o}">${esc(lvlLabel(o))}</span>
    <button class="btn small" data-action="editprofile">Edit profile</button>`;
}
function renderTabs() {
  $('#tabs').innerHTML = tabsDef().map(([id, label]) =>
    `<button class="tab ${S.tab === id ? 'active' : ''}" data-action="tab" data-arg="${id}">${label}</button>`).join('');
}
function renderTab() {
  const fn = { overview: tabOverview, sensors: tabSensors, symptoms: tabSymptoms, dx: tabDx, sim: tabSim, hist: tabHist, predict: tabPredict }[S.tab];
  Promise.resolve(fn()).catch(e => toast(e.message));
}

/* ---------------------------------------------------------------------- overview */
function bannerHtml() {
  const a = S.data.assessment, o = a.overall;
  const icon = { NORMAL: '✅', MONITOR: '👁️', SUSPECTED: '🟡', URGENT: '🟠', EMERGENCY: '🚨' }[o];
  let html = `<div class="banner lvl-${o}"><div class="big">${icon}</div><div><h2>${esc(lvlLabel(o))}</h2>
    <div>${esc(o === 'NORMAL' ? 'All available measurements are within configured limits and no symptoms are selected.' : (T().level_help[o] || ''))}</div></div></div>`;
  const subs = [];
  if (a.environment_alert) subs.push(`<div class="sub-alert lvl-ENVIRONMENT_ALERT"><b>${esc(lvlLabel('ENVIRONMENT_ALERT'))}:</b>
    ${esc(T().level_help.ENVIRONMENT_ALERT)} Notify the crew / ECLSS and move to a better-ventilated area.</div>`);
  if (a.team_support) subs.push(`<div class="sub-alert lvl-TEAM_SUPPORT"><b>${esc(lvlLabel('TEAM_SUPPORT'))}:</b> ${esc(T().level_help.TEAM_SUPPORT)}</div>`);
  const noRule = a.signals.filter(s => s.status === 'critical');
  if (noRule.length) subs.push(`<div class="sub-alert st-critical"><b>Critical sensor reading:</b>
    ${noRule.map(s => `${esc(sigLabel(s.key))} = ${fmt(s.value)} ${esc(s.unit)}`).join(' · ')}.
    Notify the designated crew medical officer.</div>`);
  a.info_alerts.forEach(i => subs.push(`<div class="sub-alert lvl-URGENT"><b>Potential ventricular arrhythmia risk:</b>
    heart rate ${fmt(i.value)} ${esc(i.unit)} (NASA threshold ≥ 110).</div>`));
  return html + (subs.length ? `<div class="sub-alerts">${subs.join('')}</div>` : '');
}
function tabOverview() {
  const a = S.data.assessment, byKey = Object.fromEntries(a.signals.map(s => [s.key, s]));
  const main = MAIN_VITALS.map(k => byKey[k]).filter(Boolean);
  const others = a.signals.filter(s => !MAIN_VITALS.includes(s.key) && s.key !== 'vomiting_episodes');
  const flagged = a.findings.slice(0, 4);
  const mr = S.data.profile.medical_record || {}; const mh = mr.medical_history || {}; const allergies = (mh.allergies || []).join(', ') || 'None recorded'; const past = (mh.past_conditions || []).join(', ') || 'None recorded';
  $('#content').innerHTML = `${bannerHtml()}
    <div class="section"><h3>Vitals & environment</h3><small>The marker shows the value relative to the configured reference thresholds.</small></div>
    <div class="grid vitals">${main.map(s => tile(s)).join('')}</div>
    ${flagged.length ? `<div class="section"><h3>Items requiring attention</h3></div>
      ${flagged.map(f => `<div class="sub-alert lvl-${f.level}" style="margin-bottom:8px">
        <span class="pill lvl-${f.level}">${esc(lvlLabel(f.level))}</span>
        <b style="margin-left:8px">${esc(findingName(f))}</b>
        <button class="btn small" style="float:right" data-action="openfinding" data-arg="${f.rule_id}">View guidance →</button></div>`).join('')}` : ''}
    <div class="section"><h3>Blood panel & radiation</h3></div>
    <div class="grid mini">${others.map(s => tile(s, true)).join('')}</div>
    <div class="section"><h3>Crew medical record</h3></div><div class="card"><div class="grid mini"><div><small>Allergies</small><b>${esc(allergies)}</b></div><div><small>Past conditions</small><b>${esc(past)}</b></div><div><small>Current medications</small><b>${esc((mh.current_medications || []).join(', ') || 'None recorded')}</b></div></div></div><p class="note">${esc(a.disclaimer)}</p>`;
}
const findingName = f => (f.red_flag_only ? 'Not benign: ' : f.escalation_only ? 'Warning sign · ' : '') + condName(f.rule_id);

/* ---------------------------------------------------------------------- sensors */
function tabSensors() {
  const a = S.data.assessment, st = S.data.state.readings, sm = Object.fromEntries(a.signals.map(s => [s.key, s]));
  const groups = {};
  S.meta.readings.forEach(r => (groups[r.category] = groups[r.category] || []).push(r));
  const field = (key, unit) => {
    const s = sm[key];
    return `<div class="field ${s ? 'st-' + s.status : ''}"><label>${esc(sigLabel(key))} (${esc(unit)})</label>
      <input type="number" step="any" data-reading="${key}" value="${st[key] ?? ''}" placeholder="—"></div>`;
  };
  $('#content').innerHTML = `
    <p class="note">Values are received from sensors. You can adjust them or use Simulation. Leave a field empty when no reading is available.</p>
    ${CAT_ORDER.filter(c => groups[c]).map(c => `
      <div class="section"><h3>${esc(T().categories[c] || c)}</h3></div>
      <div class="fields">${groups[c].map(r => field(r.key, r.unit)).join('')}</div>`).join('')}
    <div class="section"><h3>Manually entered measurements</h3><small>These are not sensor inputs but are used by the rules.</small></div>
    <div class="fields">${DERIVED_INPUTS.map(k => `<div class="field"><label>${esc(sigLabel(k))} (${esc(DERIVED_UNITS[k])})</label>
      <input type="number" step="any" data-reading="${k}" value="${st[k] ?? ''}" placeholder="—"></div>`).join('')}</div>`;
}

/* --------------------------------------------------------------------- symptoms */
function previewHtml() {
  const a = S.data.assessment;
  const top = a.findings.slice(0, 3).map(f => `<span class="pill lvl-${f.level}">${esc(findingName(f))}</span>`).join(' ');
  return `<span class="pill lvl-${a.overall}">${esc(lvlLabel(a.overall))}</span>${top ||
    '<small>Select the symptoms you are experiencing — no typing is required.</small>'}`;
}
function tabSymptoms() {
  const st = S.data.state, sel = new Set(st.symptoms), ctx = new Set(st.context);
  const chip = (id, label, on, kind) => `<button class="chip ${kind === 'ctx' ? 'ctx' : ''} ${on ? 'on' : ''}" data-${kind}="${id}"
     data-label="${esc(label.toLowerCase())}">${esc(label)}</button>`;
  $('#content').innerHTML = `
    <div class="preview"><div id="preview" class="row">${previewHtml()}</div>
      <input type="search" id="sym-search" placeholder="Search symptoms…" value="${esc(S.search)}">
      <button class="btn small" data-action="clearsym">Clear selections</button></div>
    <div class="sym-group"><h4>Context / event</h4>
      <div class="chips">${S.meta.context.map(c => chip(c, ctxLabel(c), ctx.has(c), 'ctx')).join('')}</div></div>
    ${T().symptom_groups.map(g => `<div class="sym-group"><h4>${esc(g.label)} ${g.private ? '🔒' : ''}
      <small>${g.symptoms.filter(s => sel.has(s)).length ? '· ' + g.symptoms.filter(s => sel.has(s)).length + ' selected' : ''}</small></h4>
      <div class="chips">${g.symptoms.map(s => chip(s, symLabel(s), sel.has(s), 'sym')).join('')}</div></div>`).join('')}`;
  applySearch();
}
function applySearch() {
  const q = S.search.trim().toLowerCase();
  document.querySelectorAll('.chip[data-label]').forEach(c => c.classList.toggle('hidden', !!q && !c.dataset.label.includes(q)));
}

/* --------------------------------------------------------------------- diagnosis */
const QT_TEXT = {
  qt_missing: () => 'No QTc reading: measure QTc before any medication that may affect QT.',
  qt_caution: w => `QTc is borderline (${fmt(w.value)} ms): check interactions before any medication.`,
  qt_critical: w => `QTc is CRITICAL (${fmt(w.value)} ms): do not administer QT-prolonging medication without medical direction.`,
};
function evidenceChips(f) {
  const seen = new Set();
  return f.evidence.map(e => {
    let t;
    if (e.kind === 'symptom') t = symLabel(e.id);
    else if (e.kind === 'context') t = ctxLabel(e.id);
    else t = `${sigLabel(e.key)}: ${fmt(e.value)} ${unitOf(e.key)}`;
    if (seen.has(t)) return ''; seen.add(t);
    return `<span class="chip static">${esc(t)}</span>`;
  }).join('');
}
function findingHtml(f) {
  const open = ['EMERGENCY', 'URGENT', 'ENVIRONMENT_ALERT'].includes(f.level) || S.openRule === f.rule_id;
  const med = f.medication, dose = med.specific_dose;
  const list = (items, tag = 'ul') => items && items.length ? `<${tag}>${items.map(i => `<li>${esc(i)}</li>`).join('')}</${tag}>` : '';
  return `<details class="finding lvl-${f.level}" id="f-${f.rule_id}" ${open ? 'open' : ''}>
    <summary><span class="pill lvl-${f.level}">${esc(lvlLabel(f.level))}</span>
      <span class="name">${esc(findingName(f))}</span><span class="grp">${esc(T().groups[f.group] || f.group)}</span>
      ${f.privacy_sensitive ? '<span class="chip static">🔒 private</span>' : ''}
      ${f.red_flag ? '<span class="chip static" style="border-color:#ff3b3b">🚩 red flag</span>' : ''}</summary>
    <div class="body">
      ${f.privacy_sensitive ? '<div class="box lock">🔒 Private information. Do not share without a clear safety need. Offer a confidential conversation with the crew member.</div>' : ''}
      ${f.red_flag ? `<div class="box red">🚩 <b>Red flag:</b> ${esc(f.red_flag_text || '')}<br>
        <small>The level “${esc(lvlLabel('URGENT'))}” is assigned by the software and is not specified by the source.</small></div>` : ''}
      <div><h4>Why this appeared</h4><div class="chips">${evidenceChips(f) || '<small>—</small>'}</div>
        ${f.supporting_evidence_met ? '<p class="note">✔ Supporting findings are also present (e.g. blood pressure drop / tachycardia).</p>' : ''}
        ${f.severity_markers.length ? `<p class="note">⚠ ${f.severity_markers.map(esc).join(' · ')}</p>` : ''}</div>
      ${f.steps.length ? `<div><h4>What to do now</h4>${list(f.steps, 'ol')}</div>`
        : '<div class="box warn">Seek medical assessment. Do not follow instructions intended for a mild presentation.</div>'}
      ${f.escalation_only ? '<div class="box warn">An escalation marker appeared without all criteria for the condition being met. Treat it as a warning and seek medical assessment.</div>' : ''}
      ${f.escalation ? `<div class="box warn"><b>Escalation to ${esc(lvlLabel(f.escalation.level))}:</b> ${esc(f.escalation.when)}</div>` : ''}
      ${med.summary && !f.hide_therapy ? `<div class="box"><h4>Medication</h4><p style="margin:0 0 6px">${esc(med.summary)}</p>
        ${dose ? `<table><tr><th>Medication</th><th>Dose</th><th>Route</th><th>Repeat</th></tr><tr><td>${esc(dose.drug)}</td><td>${esc(dose.dose)}</td>
          <td>${esc(dose.route)}</td><td>${esc(dose.repeat)}</td></tr></table>
          <p class="note">${esc(dose.basis)}. Typical terrestrial use, not an approved mission dose.</p>` : ''}
        ${med.warnings.map(w => `<p style="color:var(--suspected);margin:6px 0 0">⚠ ${esc(QT_TEXT[w.code](w))}</p>`).join('')}
        ${med.requires_mission_sop ? '<p class="note">An approved mission SOP / crew medical officer is required.</p>' : ''}</div>` : ''}
      ${f.do_not.length ? `<div class="box red"><h4>DO NOT</h4>${list(f.do_not)}</div>` : ''}
      ${f.kit.length ? `<div><h4>Equipment / medical kit</h4><div class="chips">${f.kit.map(k => `<span class="chip static">${esc(k)}</span>`).join('')}</div></div>` : ''}
      ${f.confirmation.length ? `<div><h4>How to confirm</h4>${list(f.confirmation)}</div>` : ''}
      <p class="note">${f.timing.description ? esc(f.timing.description) + ' · ' : ''}${f.timing.in_typical_window === true ? 'Within the typical onset window. · ' : ''}${f.incidence ? esc(f.incidence) + ' · ' : ''}${f.limitations ? esc(f.limitations) + ' · ' : ''}
        ${f.source && f.source.url ? `Source: <a href="${esc(f.source.url)}" target="_blank" rel="noopener" style="color:var(--accent)">${esc(f.source.reference)}</a>` : ''}</p>
    </div></details>`;
}
function tabDx() {
  const a = S.data.assessment;
  $('#content').innerHTML = `${bannerHtml()}
    ${a.findings.length ? a.findings.map(findingHtml).join('') :
      '<div class="card">No suspected condition was identified. Select symptoms or run a simulation to exercise the rules.</div>'}
    <p class="note">Actions and treatment references are taken from the supplied rule files. The software provides a suspected condition and alert level, never a definitive diagnosis.</p>`;
  if (S.openRule) { const el = $('#f-' + S.openRule); if (el) el.scrollIntoView({ block: 'start' }); S.openRule = null; }
}

/* ------------------------------------------------------------------- simulation */
function tabSim() {
  const rules = S.meta.rules;
  $('#content').innerHTML = `
    <p class="note">Generate synthetic sensor readings and symptoms for testing. All generated data is simulated.</p>
    <div class="section"><h3>Sensor values</h3></div>
    <div class="row">
      <button class="btn" data-action="sim" data-arg="nominal">✅ Nominal</button>
      <button class="btn" data-action="sim" data-arg="mild">🟡 Mild deviations</button>
      <button class="btn" data-action="sim" data-arg="critical">🔴 Critical values</button>
      <button class="btn" data-action="sim" data-arg="chaos">🎲 Random values</button>
    </div>
    <div class="section"><h3>Scenarios (symptoms + readings)</h3></div>
    <div class="row"><button class="btn primary" data-action="sim" data-arg="event">🎯 Random scenario</button>
      <span class="note">or choose a specific rule:</span>
      <select id="evt-rule">${rules.map(r => `<option value="${r.id}">${r.id} · ${esc(condName(r.id))}</option>`).join('')}</select>
      <select id="evt-level"></select>
      <button class="btn" data-action="simevent">Generate</button></div>
    <div class="section"><h3>Live sensor stream</h3></div>
    <div class="row"><label><input type="checkbox" id="live" ${S.live ? 'checked' : ''}> Generate new readings every 4 sec (keep symptoms)</label>
      <select id="live-mode"><option value="nominal">Nominal</option><option value="mild">Mild deviations</option><option value="chaos">Random</option></select></div>
    <div class="section"><h3>Reset</h3></div>
    <button class="btn danger" data-action="reset">Clear symptoms & restore nominal readings</button>
    <p class="note">For repeatable tests, set a seed (optional): <input type="number" id="seed" style="width:130px" placeholder="random"></p>`;
  fillLevels();
}
function fillLevels() {
  const r = S.meta.rules.find(x => x.id === $('#evt-rule').value);
  $('#evt-level').innerHTML = r.levels.map(l => `<option value="${l}">${esc(lvlLabel(l))}</option>`).join('');
}

/* ---------------------------------------------------------------------- history */
async function tabHist() {
  $('#content').innerHTML = '<div class="empty">Loading…</div>';
  const id = S.id, h = await api('GET', `/astronauts/${id}/history`);
  if (id !== S.id || S.tab !== 'hist') return;
  const hr = h.map(x => x.vitals.heart_rate).filter(v => v != null);
  let spark = '';
  if (hr.length > 1) {
    const lo = Math.min(...hr) - 5, hi = Math.max(...hr) + 5, W = 700, H = 90;
    const pts = hr.map((v, i) => `${(i / (hr.length - 1)) * W},${H - ((v - lo) / (hi - lo)) * H}`).join(' ');
    spark = `<div class="card"><small>Heart rate (bpm) · ${hr.length} records</small>
      <svg viewBox="0 0 ${W} ${H}" width="100%" height="90" preserveAspectRatio="none"><polyline fill="none" stroke="#4cc9f0" stroke-width="2" points="${pts}"/></svg></div>`;
  }
  const srcL = { manual: 'Manual', simulation: 'Simulation', system: 'System' };
  $('#content').innerHTML = `${spark}<div class="section"><h3>Records</h3></div>
    <div class="card" style="overflow-x:auto"><table><tr><th>Timestamp</th><th>Source</th><th>Status</th><th>Findings</th><th>HR</th><th>BP</th><th>SpO2</th></tr>
    ${h.slice().reverse().slice(0, 60).map(x => `<tr><td>${esc(new Date(x.ts).toLocaleString('el-GR'))}</td><td>${esc(srcL[x.source] || x.source)}</td>
      <td><span class="pill lvl-${x.overall}">${esc(lvlLabel(x.overall))}</span></td>
      <td>${x.findings.map(f => x.findings && f.private ? '🔒' : esc(condName(f.id))).join(', ') || '—'}</td>
      <td>${fmt(x.vitals.heart_rate)}</td><td>${fmt(x.vitals.blood_pressure_systolic)}/${fmt(x.vitals.blood_pressure_diastolic)}</td>
      <td>${fmt(x.vitals.spo2)}</td></tr>`).join('')}</table></div>`;
}


/* ---------------------------------------------------------------------- trend forecast (screening aid, not diagnosis) */
async function tabPredict() {
  const h = await api('GET', `/astronauts/${S.id}/history`);
  const metrics = [['heart_rate','Heart rate','bpm'],['spo2','Oxygen saturation','%'],['blood_pressure_systolic','Systolic BP','mmHg'],['skin_temperature','Skin temperature','°C']];
  const cards = metrics.map(([key,label,unit]) => {
    const vals = h.map(x => x.vitals[key]).filter(v => Number.isFinite(v));
    if (vals.length < 3) return `<div class="card"><b>${label}</b><p class="note">Not enough history yet. At least 3 recorded measurements are needed.</p></div>`;
    const recent = vals.slice(-8), first = recent[0], last = recent[recent.length-1];
    const delta = last-first, direction = Math.abs(delta)<0.5 ? 'Stable' : delta>0 ? 'Trending upward' : 'Trending downward';
    const projected = last + (delta / Math.max(1,recent.length-1))*3;
    return `<div class="card"><div class="section"><b>${label}</b><span class="pill">${direction}</span></div><div class="t-val">${fmt(last)} <small>${unit}</small></div><p class="note">Recent change: ${delta>0?'+':''}${fmt(delta)} ${unit}. Simple 3-step trend estimate: ${fmt(projected)} ${unit}.</p></div>`;
  }).join('');
  $('#content').innerHTML = `<div class="banner lvl-MONITOR"><div class="big">📈</div><div><h2>Personal trend outlook</h2><div>Exploratory trend estimates from this astronaut's recorded history. Not a diagnosis or a validated prediction model.</div></div></div><div class="grid">${cards}</div><p class="note">Forecasts use a simple recent linear trend and may be misleading with sparse, noisy, simulated, or changing-condition data. Use validated mission-specific models before operational use.</p>`;
}

/* ---------------------------------------------------------------------- profile */
function openProfile(edit) {
  const p = edit ? S.data.profile : { name: '', sex: 'female', age: 35, role: '', mission_day: 1, mission_duration_days: 180 };
  const dlg = $('#profile-dialog');
  dlg.innerHTML = `<form method="dialog" id="pform"><h2>${edit ? 'Edit profile' : '＋ Add astronaut'}</h2>
    <div class="field"><label>Name</label><input type="text" name="name" required maxlength="60" value="${esc(p.name)}"></div>
    <div class="field"><label>Role</label><input type="text" name="role" maxlength="60" value="${esc(p.role)}"></div>
    <div class="row"><div class="field"><label>Sex (used for blood/QTc reference limits)</label><select name="sex">
      <option value="female" ${p.sex === 'female' ? 'selected' : ''}>Female</option><option value="male" ${p.sex === 'male' ? 'selected' : ''}>Male</option></select></div>
      <div class="field"><label>Age</label><input type="number" name="age" min="18" max="80" value="${p.age}"></div></div>
    <div class="row"><div class="field"><label>Mission day</label><input type="number" name="mission_day" min="0" value="${p.mission_day}"></div>
      <div class="field"><label>Duration (days)</label><input type="number" name="mission_duration_days" min="1" value="${p.mission_duration_days}"></div></div>
    <div class="row" style="justify-content:space-between"><span>${edit ? '<button type="button" class="btn danger" id="pdel">Delete</button>' : ''}</span>
      <span class="row"><button type="button" class="btn" id="pcancel">Cancel</button><button class="btn primary" value="ok">Save</button></span></div></form>`;
  dlg.showModal();
  $('#pcancel').onclick = () => dlg.close();
  if (edit) $('#pdel').onclick = guard(async () => {
    if (!confirm('Delete profile ' + p.name + ';')) return;
    await api('DELETE', '/astronauts/' + S.id); dlg.close();
    await refreshList(); S.id = null; S.data = null;
    if (S.list.length) await select(S.list[0].id); else { renderSidebar(); renderMain(); }
  });
  $('#pform').onsubmit = guard(async e => {
    const f = Object.fromEntries(new FormData(e.target));
    ['age', 'mission_day', 'mission_duration_days'].forEach(k => f[k] = Number(f[k]));
    if (edit) { S.data = await api('PUT', '/astronauts/' + S.id, f); await refreshList(); renderSidebar(); renderMain(); }
    else { const n = await api('POST', '/astronauts', f); await refreshList(); await select(n.id); }
  });
}

/* ---------------------------------------------------------------- data + actions */
async function refreshList() { S.list = await api('GET', '/astronauts'); }
async function select(id) {
  S.id = id; S.data = await api('GET', '/astronauts/' + id); renderSidebar(); renderMain();
}
function afterUpdate() {
  renderSidebar(); renderHead(); renderTabs();
  if (S.tab === 'symptoms') { const p = $('#preview'); if (p) p.innerHTML = previewHtml(); }
  else if (S.tab === 'sensors') { /* keep focus in inputs; recolor borders */
    const sm = Object.fromEntries(S.data.assessment.signals.map(s => [s.key, s]));
    document.querySelectorAll('[data-reading]').forEach(i => {
      const f = i.closest('.field'); f.className = 'field' + (sm[i.dataset.reading] ? ' st-' + sm[i.dataset.reading].status : '');
    });
  } else renderTab();
}
async function saveState(payload) {
  const id = S.id;
  const res = await api('PUT', `/astronauts/${id}/state`, payload);
  if (id !== S.id) return;
  S.data = res; await refreshList(); afterUpdate();
}
function scheduleSave() {
  clearTimeout(S.saveTimer);
  S.saveTimer = setTimeout(guard(() => saveState({ symptoms: S.data.state.symptoms, context: S.data.state.context })), 300);
}
async function simulate(mode, extra = {}) {
  const seedEl = $('#seed'), body = { mode, ...extra };
  if (seedEl && seedEl.value !== '') body.seed = parseInt(seedEl.value, 10);
  const res = await api('POST', `/astronauts/${S.id}/simulate`, body);
  S.data = res; await refreshList(); renderSidebar(); renderHead(); renderTabs();
  if (extra.keep_symptoms) { if (S.tab !== 'symptoms') renderTab(); return; }
  S.tab = 'dx'; renderTabs(); renderTab();
  if (res.simulation) toast(`${res.simulation.description} (seed ${res.simulation.seed})`);
}
function toggleLive(on) {
  clearInterval(S.live); S.live = null;
  if (on) S.live = setInterval(() => { if (S.id) simulate($('#live-mode') ? $('#live-mode').value : 'nominal',
    { keep_symptoms: true }).catch(() => {}); }, 4000);
}

document.addEventListener('click', guard(async e => {
  const chip = e.target.closest('[data-sym],[data-ctx]');
  if (chip) {
    const kind = chip.dataset.sym ? 'symptoms' : 'context', id = chip.dataset.sym || chip.dataset.ctx;
    const set = new Set(S.data.state[kind]); set.has(id) ? set.delete(id) : set.add(id);
    S.data.state[kind] = [...set]; chip.classList.toggle('on'); scheduleSave(); return;
  }
  const b = e.target.closest('[data-action]'); if (!b) return;
  const arg = b.dataset.arg;
  switch (b.dataset.action) {
    case 'select': await select(arg); break;
    case 'tab': S.tab = arg; renderTabs(); renderTab(); break;
    case 'newprofile': openProfile(false); break;
    case 'importprofile': $('#profile-import').click(); break;
    case 'importdatabase': $('#database-import').click(); break;
    case 'editprofile': openProfile(true); break;
    case 'openfinding': S.openRule = arg; S.tab = 'dx'; renderTabs(); renderTab(); break;
    case 'clearsym': S.data.state.symptoms = []; S.data.state.context = []; document.querySelectorAll('.chip.on').forEach(c => c.classList.remove('on')); scheduleSave(); break;
    case 'sim': await simulate(arg); break;
    case 'simevent': await simulate('event', { rule_id: $('#evt-rule').value, level: $('#evt-level').value }); break;
    case 'reset': await simulate('nominal'); break;
  }
}));
document.addEventListener('change', guard(async e => {
  const t = e.target;
  if (t.dataset && t.dataset.reading) {
    const v = t.value === '' ? null : Number(t.value);
    await saveState({ readings: { [t.dataset.reading]: v } });
  } else if (t.id === 'evt-rule') fillLevels();
  else if (t.id === 'live') toggleLive(t.checked);
}));
document.addEventListener('input', e => {
  if (e.target.id === 'sym-search') { S.search = e.target.value; applySearch(); }
});

document.addEventListener('change', guard(async e => {
  if (e.target.id === 'database-import' && e.target.files.length) {
    const file = e.target.files[0]; const doc = JSON.parse(await file.text());
    const result = await api('POST','/database/import',{data:doc});
    S.meta = await api('GET','/meta'); S.meta.i18n.conditions = Object.fromEntries(S.meta.rules.map(r => [r.id, r.name])); await refreshList(); if (S.id) await select(S.id);
    toast(`Database updated: ${result.file} · ${result.rules} rules · ${result.signals} signals`); e.target.value=''; return;
  }
}));

document.addEventListener('change', guard(async e => {
  if (e.target.id !== 'profile-import' || !e.target.files.length) return;
  const file = e.target.files[0]; const obj = JSON.parse(await file.text());
  const personal = obj.personal_information || {}; const med = obj.medical_history || {};
  const baseline = obj.pre_flight_baseline || {};
  const cv = baseline.cardiovascular || {};
  const profile = { astronaut_id: obj.astronaut_id || '', name: obj.name || `Astronaut ${obj.astronaut_id || ''}`,
    sex: String(personal.gender || 'male').toLowerCase().startsWith('f') ? 'female' : 'male',
    age: personal.age || 35, role: obj.role || 'Crew member', mission_day: 1, mission_duration_days: 180,
    medical_record: { personal_information: personal, medical_history: med, pre_flight_baseline: baseline } };
  const created = await api('POST','/astronauts',profile); await refreshList(); await select(created.id);
  toast(`Imported medical record for ${profile.name} (${created.id})`); e.target.value='';
}));

(guard(async () => {
  S.meta = await api('GET', '/meta');
  await refreshList();
  if (S.list.length) await select(S.list[0].id); else { renderSidebar(); renderMain(); }
}))();
