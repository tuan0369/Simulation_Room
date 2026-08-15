#!/usr/bin/env node
'use strict';

const pptxgen = require('pptxgenjs');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');

const OUT = __dirname;
const PPTX = path.join(OUT, 'EcoHVAC_Guardian_Project2_Pitch.pptx');
const C = {
  navy: '14213D', blue: '2B6CB0', orange: 'D97706', green: '14866D', purple: '7C3AED',
  ink: '172033', muted: '596579', faint: 'E7ECF2', panel: 'F5F7FA', white: 'FFFFFF',
  amber: '9A6700', amberBg: 'FFF4D6', red: 'B42318', redBg: 'FDECEA', tealBg: 'E8F5F1',
  blueBg: 'EAF2FB', purpleBg: 'F2ECFF', dark: '0D172A', dark2: '16243C', steel: 'A9B5C7',
  gray: '7B8798', black: '000000'
};
const FONT = 'Arial';
const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'Project 2 pitch generator';
pptx.company = '';
pptx.subject = 'Governed evidence-hardening pitch';
pptx.title = 'EcoHVAC Guardian Project 2 Pitch';
pptx.lang = 'en-SG';
pptx.theme = { headFontFace: FONT, bodyFontFace: FONT, lang: 'en-SG' };
pptx.defineSlideMaster({
  title: 'MASTER', background: { color: C.white },
  objects: [
    { line: { x: 0.45, y: 7.08, w: 12.43, h: 0, line: { color: C.faint, width: 1 } } },
    { text: { text: 'ECOHVAC GUARDIAN  |  GOVERNED EVIDENCE-HARDENING CASE', options: { x: 0.55, y: 7.14, w: 7.4, h: 0.18, fontFace: FONT, fontSize: 6.8, color: C.gray, charSpacing: 1.1, margin: 0, fit: 'shrink' } } },
    { text: { text: 'ROI  ·  CYBERSECURITY  ·  ETHICAL SAFETY', options: { x: 9.22, y: 7.14, w: 3.55, h: 0.18, align: 'right', fontFace: FONT, fontSize: 6.8, color: C.gray, charSpacing: 0.9, margin: 0, fit: 'shrink' } } }
  ],
  slideNumber: { x: 12.88, y: 7.13, color: C.gray, fontFace: FONT, fontSize: 7 }
});

function addText(s, text, x, y, w, h, size = 20, color = C.ink, bold = false, opts = {}) {
  s.addText(text, {
    x, y, w, h, fontFace: FONT, fontSize: size, color, bold, margin: opts.margin ?? 0,
    breakLine: false, fit: opts.fit || 'shrink', valign: opts.valign || 'mid',
    align: opts.align || 'left', bullet: opts.bullet, paraSpaceAfterPt: opts.paraSpaceAfterPt || 0,
    charSpacing: opts.charSpacing || 0, isTextBox: true, transparency: opts.transparency || 0,
    italic: opts.italic || false
  });
}
function rect(s, x, y, w, h, fill = C.panel, outline = C.faint, radius = 0.08) {
  s.addShape(pptx.ShapeType.roundRect, { x, y, w, h, rectRadius: radius, fill: { color: fill }, line: { color: outline, width: 1 } });
}
function line(s, x, y, w, h, color = C.faint, width = 1, dash = 'solid', beginArrowType, endArrowType) {
  s.addShape(pptx.ShapeType.line, { x, y, w, h, line: { color, width, dashType: dash, beginArrowType, endArrowType } });
}
function pill(s, text, x, y, w, fill, color, outline = fill) {
  s.addShape(pptx.ShapeType.roundRect, { x, y, w, h: 0.32, rectRadius: 0.14, fill: { color: fill }, line: { color: outline, width: 0.8 } });
  addText(s, text, x + 0.06, y + 0.03, w - 0.12, 0.25, 8.5, color, true, { align: 'center', charSpacing: 0.5 });
}
function dot(s, x, y, size, color) {
  s.addShape(pptx.ShapeType.ellipse, { x, y, w: size, h: size, fill: { color }, line: { color } });
}
function title(s, kicker, headline, sub) {
  addText(s, kicker.toUpperCase(), 0.58, 0.32, 4.5, 0.22, 9, C.blue, true, { charSpacing: 1.8 });
  addText(s, headline, 0.58, 0.63, 12.08, 0.72, 27.5, C.navy, true);
  if (sub) addText(s, sub, 0.58, 1.39, 12.0, 0.36, 12, C.muted, false);
}
function claimType(s, kind, x, y, w) {
  const styles = {
    current: ['CURRENT / IMPLEMENTED', C.blueBg, C.blue, 'A8C9EB'],
    illustrative: ['ILLUSTRATIVE / ASSUMPTION', C.amberBg, C.amber, 'E6C45C'],
    target: ['TARGET / REQUIRED', C.tealBg, C.green, '9AC9B9'],
    gate: ['GATE / NO-GO RULE', C.redBg, C.red, 'E89993']
  };
  const a = styles[kind]; pill(s, a[0], x, y, w, a[1], a[2], a[3]);
}
function boundaryStrip(s, dark = false) {
  const fill = dark ? C.dark2 : 'EEF2F7';
  const outline = dark ? '29405F' : 'D9E0E8';
  const color = dark ? C.steel : C.muted;
  rect(s, 0.58, 6.48, 12.08, 0.34, fill, outline);
  addText(s, 'SIMULATION-ONLY  ·  NO FACILITY MEASUREMENTS  ·  NO REAL ROI  ·  NO PRODUCTION SECURITY  ·  NO PHYSICAL AUTONOMY', 0.78, 6.55, 11.68, 0.18, 7.8, color, true, { align: 'center', charSpacing: 0.45 });
}
function source(s, text, dark = false) {
  addText(s, text, 0.58, 6.86, 11.95, 0.16, 6.8, dark ? C.steel : C.gray, false, { align: 'right' });
}
function notes(s, lines) { s.addNotes(lines.join('\n')); }
function metricTile(s, x, y, w, h, value, label, color = C.navy, fill = C.white, outline = C.faint) {
  rect(s, x, y, w, h, fill, outline);
  addText(s, value, x + 0.14, y + 0.13, w - 0.28, h * 0.44, 23, color, true, { align: 'center' });
  addText(s, label, x + 0.14, y + h * 0.60, w - 0.28, h * 0.20, 9, C.muted, true, { align: 'center', charSpacing: 0.4 });
}
function numberCircle(s, n, x, y, color) {
  s.addShape(pptx.ShapeType.ellipse, { x, y, w: 0.43, h: 0.43, fill: { color }, line: { color } });
  addText(s, String(n), x, y + 0.02, 0.43, 0.34, 12, C.white, true, { align: 'center' });
}

// Slide 1 — investment thesis
{
  const s = pptx.addSlide('MASTER');
  s.background = { color: C.dark };
  s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 13.333, h: 7.5, fill: { color: C.dark }, line: { color: C.dark } });
  s.addShape(pptx.ShapeType.arc, { x: 8.45, y: -2.15, w: 7.3, h: 7.3, adjustPoint: 0.24, rotate: 8, line: { color: C.blue, width: 30, transparency: 18 }, fill: { color: C.dark, transparency: 100 } });
  s.addShape(pptx.ShapeType.arc, { x: 9.2, y: -0.7, w: 5.2, h: 5.2, adjustPoint: 0.24, rotate: 12, line: { color: C.green, width: 18, transparency: 18 }, fill: { color: C.dark, transparency: 100 } });
  pill(s, 'EXECUTIVE DECISION', 0.7, 0.55, 1.9, C.blue, C.white, C.blue);
  addText(s, 'Test the value.\nProtect the system.\nKeep people in control.', 0.7, 1.2, 6.0, 2.2, 31, C.white, true);
  addText(s, 'A governed pilot can test an illustrative S$9,080/year value hypothesis without connecting autonomous control to a real building.', 0.72, 3.56, 6.15, 0.95, 15, C.steel, false);
  const pillars = [
    ['ROI', 'Resolve what drives value', C.orange, '01'],
    ['SECURITY', 'Earn permission to connect', C.blue, '02'],
    ['ETHICAL SAFETY', 'Bound burden and authority', C.green, '03']
  ];
  pillars.forEach((a, i) => {
    const y = 1.32 + i * 1.45;
    rect(s, 7.55, y, 4.7, 1.13, C.dark2, '29405F');
    addText(s, a[3], 7.84, y + 0.18, 0.52, 0.48, 20, a[2], true);
    addText(s, a[0], 8.55, y + 0.16, 3.15, 0.27, 12, a[2], true, { charSpacing: 1 });
    addText(s, a[1], 8.55, y + 0.5, 3.15, 0.34, 15, C.white, true);
  });
  rect(s, 0.72, 5.2, 6.15, 0.72, C.dark2, '29405F');
  addText(s, 'THREE VETO GATES', 0.98, 5.34, 1.58, 0.22, 9, C.orange, true, { charSpacing: 1 });
  addText(s, 'No financial upside overrides a failed security or ethical-safety gate.', 2.75, 5.25, 3.78, 0.42, 12.5, C.white, true);
  claimType(s, 'illustrative', 7.55, 5.42, 2.2);
  claimType(s, 'current', 9.95, 5.42, 2.18);
  boundaryStrip(s, true);
  source(s, 'Sources: dashboard/presentation.py; report Chapters 7–8; current simulator boundary.', true);
  notes(s, [
    'Open with the decision: test value only while security and ethical safety remain veto gates.',
    'S$9,080/year is illustrative arithmetic from editable assumptions, not measured savings or a forecast.',
    'The current artifact is a classroom simulation; do not imply production approval, physical autonomy, or a funded deployment.'
  ]);
}

// Slide 2 — ROI equation
{
  const s = pptx.addSlide('MASTER');
  title(s, 'ROI · Value equation', 'The base case works only if avoided incidents are real.', 'Under the editable scenario, maintenance avoidance supplies 92% of gross modeled benefit; energy contributes S$1,080/year.');
  claimType(s, 'illustrative', 0.62, 1.87, 2.23);
  const blocks = [
    ['S$1,080', 'ENERGY SAVING', C.green, C.tealBg],
    ['+', '', C.muted, C.white],
    ['S$12,000', 'AVOIDED INCIDENTS', C.orange, C.amberBg],
    ['−', '', C.muted, C.white],
    ['S$4,000', 'ANNUAL SUPPORT', C.red, C.redBg],
    ['=', '', C.muted, C.white],
    ['S$9,080', 'ANNUAL NET BENEFIT', C.blue, C.blueBg]
  ];
  let x = 0.62;
  const widths = [2.15, 0.45, 2.35, 0.45, 2.15, 0.45, 2.45];
  blocks.forEach((a, i) => {
    if ([1, 3, 5].includes(i)) {
      addText(s, a[0], x, 2.68, widths[i], 0.55, 27, a[2], true, { align: 'center' });
    } else {
      rect(s, x, 2.3, widths[i], 1.34, a[3], a[2]);
      addText(s, a[0], x + 0.1, 2.53, widths[i] - 0.2, 0.46, 24, a[2], true, { align: 'center' });
      addText(s, a[1], x + 0.1, 3.1, widths[i] - 0.2, 0.22, 8.3, C.muted, true, { align: 'center', charSpacing: 0.55 });
    }
    x += widths[i] + 0.16;
  });
  rect(s, 0.62, 4.03, 7.82, 1.54, C.white, C.faint);
  addText(s, 'VALUE DEPENDENCY', 0.92, 4.25, 1.55, 0.24, 9, C.orange, true, { charSpacing: 0.9 });
  addText(s, '92%', 0.92, 4.57, 1.45, 0.53, 29, C.orange, true);
  addText(s, 'of gross modeled benefit comes from the unverified avoided-incident assumption.', 2.4, 4.48, 5.55, 0.55, 17, C.ink, true);
  line(s, 0.92, 5.25, 6.92, 0, C.faint, 6);
  line(s, 0.92, 5.25, 6.36, 0, C.orange, 6);
  metricTile(s, 8.72, 4.03, 1.78, 1.54, '−63.68%', 'FIRST-YEAR ROI', C.red, C.redBg, 'E89993');
  metricTile(s, 10.68, 4.03, 1.98, 1.54, '33.04 mo', 'SIMPLE PAYBACK', C.blue, C.blueBg, 'A8C9EB');
  rect(s, 0.62, 5.78, 12.04, 0.48, C.amberBg, 'E6C45C');
  addText(s, 'ARITHMETIC, NOT FORECAST', 0.88, 5.9, 2.25, 0.2, 9, C.amber, true, { charSpacing: 0.7 });
  addText(s, 'No facility baseline, applicable tariff, incident record, implementation quote, support quote, or measured reduction is attached.', 3.08, 5.85, 9.14, 0.29, 10.5, C.ink, true);
  boundaryStrip(s);
  source(s, 'Sources: dashboard/presentation.py and dashboard/app.py; report/academic-report/sections/08-roi-roadmap.tex.');
  notes(s, [
    'Explain the equation before discussing payback: S$1,080 energy saving plus S$12,000 avoided incidents minus S$4,000 support gives S$9,080 net.',
    'S$25,000 implementation yields −63.68% first-year ROI and 33.04-month simple payback under this scenario.',
    'Every number is illustrative. Do not call the result measured savings, achieved payback, NPV, or a facility business case.'
  ]);
}

// Slide 3 — ROI sensitivity
{
  const s = pptx.addSlide('MASTER');
  title(s, 'ROI · Sensitivity', 'The case ranges from no payback to 8.10 months.', 'That spread is the reason for a pilot: replace the assumptions controlling the decision, rather than selecting the favorable scenario.');
  claimType(s, 'illustrative', 0.62, 1.86, 2.23);
  const scenarios = [
    { x: 0.62, name: 'LOW', net: '−S$1,600', pay: 'NO PAYBACK', color: C.red, fill: C.redBg, outline: 'E89993' },
    { x: 4.14, name: 'BASE', net: 'S$9,080', pay: '33.04 MONTHS', color: C.blue, fill: C.blueBg, outline: 'A8C9EB' },
    { x: 7.66, name: 'HIGH', net: 'S$29,625', pay: '8.10 MONTHS', color: C.green, fill: C.tealBg, outline: '9AC9B9' }
  ];
  scenarios.forEach((a) => {
    rect(s, a.x, 2.3, 3.14, 2.2, a.fill, a.outline);
    addText(s, a.name + ' SCENARIO', a.x + 0.22, 2.53, 2.7, 0.24, 9, a.color, true, { align: 'center', charSpacing: 1.1 });
    addText(s, a.net, a.x + 0.22, 2.95, 2.7, 0.52, 25, a.color, true, { align: 'center' });
    addText(s, 'illustrative annual net', a.x + 0.22, 3.43, 2.7, 0.22, 9, C.muted, false, { align: 'center' });
    line(s, a.x + 0.35, 3.82, 2.44, 0, a.outline, 1);
    addText(s, a.pay, a.x + 0.22, 3.94, 2.7, 0.28, 12, a.color, true, { align: 'center' });
  });
  rect(s, 11.03, 2.3, 1.63, 2.2, C.amberBg, 'E6C45C');
  addText(s, 'DOMINANT\nUNCERTAINTY', 11.2, 2.58, 1.29, 0.45, 9, C.amber, true, { align: 'center', charSpacing: 0.6 });
  addText(s, 'Avoided\nincidents', 11.2, 3.24, 1.29, 0.54, 17, C.ink, true, { align: 'center' });
  addText(s, 'not energy alone', 11.2, 3.92, 1.29, 0.24, 9, C.muted, true, { align: 'center' });
  claimType(s, 'target', 0.62, 4.82, 1.68);
  addText(s, 'PILOT LEARNING AGENDA', 2.5, 4.83, 2.52, 0.3, 13, C.navy, true);
  const agenda = [
    ['01', 'Metered, weather- and occupancy-normalized baseline'],
    ['02', 'Applicable tariff and implementation/support quotes'],
    ['03', 'Incident frequency, consequence, and avoidability'],
    ['04', 'Comfort, fairness, and operator-workload outcomes']
  ];
  agenda.forEach((a, i) => {
    const col = i % 2, row = Math.floor(i / 2), bx = 0.62 + col * 6.03, by = 5.22 + row * 0.52;
    addText(s, a[0], bx, by, 0.42, 0.26, 10, C.green, true);
    addText(s, a[1], bx + 0.5, by - 0.02, 5.25, 0.3, 10.4, C.ink, true);
  });
  boundaryStrip(s);
  source(s, 'Source: illustrative low/base/high scenarios in report/academic-report/sections/08-roi-roadmap.tex.');
  notes(s, [
    'Call these scenarios, not forecasts. The low case has no economic payback; the high case must not be presented as expected.',
    'The pilot exists to resolve assumptions with evidence, especially avoided-incident value and cost.',
    'Do not invent low/high inputs that are not shown; present only the supported scenario outputs and learning agenda.'
  ]);
}

// Slide 4 — current security exposure
{
  const s = pptx.addSlide('MASTER');
  title(s, 'Cybersecurity · Current exposure', 'Do not connect real equipment through anonymous, plaintext control paths.', 'The classroom profile is useful for demonstration, but it does not establish authenticated actors, confidential transport, or independent recovery.');
  claimType(s, 'current', 0.62, 1.86, 1.87);
  const threats = [
    { x: 0.62, n: '01', head: 'ANONYMOUS PUBLISH', path: 'Actor impersonation', result: 'Unauthorized or misleading commands', color: C.red },
    { x: 4.73, n: '02', head: 'PLAINTEXT TRANSPORT', path: 'Eavesdrop or tamper', result: 'False telemetry or exposed room-use data', color: C.orange },
    { x: 8.84, n: '03', head: 'UNPROVEN RECOVERY', path: 'Broker or control-path failure', result: 'Containment or restoration may fail', color: C.purple }
  ];
  threats.forEach((a) => {
    rect(s, a.x, 2.28, 3.5, 2.35, C.white, a.color);
    numberCircle(s, a.n, a.x + 0.24, 2.52, a.color);
    addText(s, a.head, a.x + 0.83, 2.52, 2.36, 0.25, 10, a.color, true, { charSpacing: 0.75 });
    addText(s, a.path, a.x + 0.25, 3.2, 3.0, 0.36, 17, C.ink, true, { align: 'center' });
    line(s, a.x + 1.46, 3.73, 0.6, 0, a.color, 2, 'solid', undefined, 'triangle');
    addText(s, a.result, a.x + 0.25, 3.96, 3.0, 0.42, 11, C.muted, true, { align: 'center' });
  });
  addText(s, 'CURRENT LIMITED SAFEGUARDS', 0.62, 4.92, 2.62, 0.28, 11, C.navy, true, { charSpacing: 0.8 });
  const safeguards = [
    ['Strict contracts', C.blue], ['Application ACK', C.blue], ['Process-local dedupe', C.orange],
    ['Optional local hash chain', C.orange], ['Simulation pause / stop', C.green]
  ];
  safeguards.forEach((a, i) => {
    const x = 0.62 + i * 2.42;
    rect(s, x, 5.34, 2.15, 0.62, i < 2 ? C.blueBg : i < 4 ? C.amberBg : C.tealBg, C.faint);
    dot(s, x + 0.18, 5.55, 0.15, a[1]);
    addText(s, a[0], x + 0.44, 5.46, 1.5, 0.26, 9.8, C.ink, true);
  });
  rect(s, 0.62, 6.08, 12.04, 0.28, C.redBg, 'E89993');
  addText(s, 'RELIABILITY AND ACCOUNTABILITY SAFEGUARDS — NOT AUTHENTICATION, CONFIDENTIALITY, PHYSICAL FAIL-SAFE, OR PRODUCTION SECURITY', 0.79, 6.13, 11.7, 0.15, 7.9, C.red, true, { align: 'center', charSpacing: 0.35 });
  boundaryStrip(s);
  source(s, 'Sources: mosquitto/config/mosquitto.conf; simulator/contracts.py, publisher.py, audit.py and ecosystem.py.');
  notes(s, [
    'The default classroom broker permits anonymous access and uses MQTT 1883 and WebSockets 9001 in plaintext.',
    'Strict contracts, acknowledgements, process-local deduplication, optional local hash chaining, and simulation stop are implemented but are not production security.',
    'The local journal is optional, command-scoped, not externally anchored, and cannot establish non-repudiation.'
  ]);
}

// Slide 5 — security evidence gate
{
  const s = pptx.addSlide('MASTER');
  title(s, 'Cybersecurity · Deployment gate', 'Security earns permission to connect—one evidence package at a time.', 'Every required control needs implementation, an adversarial test, recovery proof, and accountable decision rights before real connectivity.');
  claimType(s, 'target', 0.62, 1.86, 1.7);
  const gates = [
    ['1', 'IDENTITY', 'Per-device identity\nor mTLS', 'Issue · revoke · rotate'],
    ['2', 'TRANSPORT', 'TLS / WSS\nend to end', 'MITM · expiry · downgrade'],
    ['3', 'AUTHORIZATION', 'Least-privilege ACL\n+ command freshness', 'Allow · deny · stale · replay'],
    ['4', 'AUDIT', 'Protected records\n+ external anchoring', 'Integrity · access · coverage'],
    ['5', 'RECOVERY', 'Independent fallback\n+ rehearsed restore', 'Isolate · rollback · recover']
  ];
  gates.forEach((a, i) => {
    const x = 0.62 + i * 2.42;
    const colors = [C.blue, C.blue, C.purple, C.orange, C.green];
    rect(s, x, 2.32, 2.15, 2.65, C.white, colors[i]);
    numberCircle(s, a[0], x + 0.2, 2.56, colors[i]);
    addText(s, a[1], x + 0.78, 2.57, 1.15, 0.23, 8.8, colors[i], true, { charSpacing: 0.7 });
    line(s, x + 0.22, 3.12, 1.7, 0, C.faint, 1);
    addText(s, a[2], x + 0.2, 3.34, 1.75, 0.64, 14, C.ink, true, { align: 'center' });
    pill(s, 'PASS EVIDENCE', x + 0.32, 4.18, 1.5, C.panel, C.gray, C.faint);
    addText(s, a[3], x + 0.22, 4.58, 1.7, 0.23, 8.8, C.muted, true, { align: 'center' });
    if (i < 4) line(s, x + 2.16, 3.61, 0.25, 0, C.gray, 1.5, 'solid', undefined, 'triangle');
  });
  rect(s, 0.62, 5.3, 12.04, 0.9, C.dark, C.dark);
  claimType(s, 'gate', 0.9, 5.58, 1.73);
  addText(s, 'NO EVIDENCE', 2.95, 5.49, 2.25, 0.35, 18, C.white, true, { align: 'center' });
  addText(s, '→', 5.18, 5.48, 0.52, 0.35, 20, C.orange, true, { align: 'center' });
  addText(s, 'NO CONNECTION', 5.72, 5.49, 2.45, 0.35, 18, C.white, true, { align: 'center' });
  addText(s, '→', 8.17, 5.48, 0.52, 0.35, 20, C.orange, true, { align: 'center' });
  addText(s, 'NO AUTOMATION', 8.72, 5.49, 2.72, 0.35, 18, C.white, true, { align: 'center' });
  addText(s, 'Future dossier: named authority · versioned test evidence · incident duties · residual-risk acceptance', 2.95, 5.88, 8.49, 0.2, 8.5, C.steel, true, { align: 'center' });
  boundaryStrip(s);
  source(s, 'Sources: current security implementation; report governance/security requirements; NIST SP 800-82 Rev. 3 as target guidance.');
  notes(s, [
    'This is a deployment gate, not a claim that TLS, ACLs, production identities, external audit anchoring, or independent fallback are deployed.',
    'Each package requires versioned test evidence and recovery proof. Do not invent owners, certificates, signatures, or approvals.',
    'Security expenditure buys progressively bounded permission to connect, not blanket permission to automate.'
  ]);
}

// Slide 6 — ethical ledger
{
  const s = pptx.addSlide('MASTER');
  title(s, 'Ethical safety · Value accounting', 'Savings count only when human burden is measured beside them.', 'Aggregate value cannot hide severe discomfort, repeated starvation, missed risk, privacy inference, or displaced accountability.');
  claimType(s, 'current', 0.62, 1.86, 1.87);
  claimType(s, 'target', 10.96, 1.86, 1.7);
  rect(s, 0.62, 2.28, 5.35, 3.42, C.tealBg, '9AC9B9');
  addText(s, 'BENEFIT TO TEST', 0.92, 2.55, 2.55, 0.28, 11, C.green, true, { charSpacing: 1 });
  addText(s, 'Economic and operational value', 0.92, 2.95, 4.55, 0.37, 18, C.ink, true);
  const benefits = ['HVAC kWh and cost', 'Maintenance incidents and downtime', 'Operator response and maintenance lead time', 'Transparent shared-air allocation'];
  benefits.forEach((t, i) => {
    dot(s, 0.94, 3.58 + i * 0.47, 0.14, C.green);
    addText(s, t, 1.25, 3.48 + i * 0.47, 4.18, 0.3, 11.2, C.ink, true);
  });
  rect(s, 7.36, 2.28, 5.3, 3.42, C.redBg, 'E89993');
  addText(s, 'BURDEN TO BOUND', 7.66, 2.55, 2.7, 0.28, 11, C.red, true, { charSpacing: 1 });
  addText(s, 'Comfort, workload, privacy and safety', 7.66, 2.95, 4.45, 0.37, 18, C.ink, true);
  const burdens = ['Comfort degree-hours and denied-flow duration', 'Maximum starvation and room-to-room disparity', 'False alerts and operator workload', 'False negatives and privacy/security exposure'];
  burdens.forEach((t, i) => {
    dot(s, 7.68, 3.58 + i * 0.47, 0.14, C.red);
    addText(s, t, 7.99, 3.48 + i * 0.47, 4.12, 0.3, 11.2, C.ink, true);
  });
  s.addShape(pptx.ShapeType.ellipse, { x: 5.73, y: 3.23, w: 1.55, h: 1.55, fill: { color: C.dark }, line: { color: C.dark } });
  addText(s, 'VALUE\nLEDGER', 5.89, 3.55, 1.23, 0.58, 14, C.white, true, { align: 'center' });
  line(s, 5.97, 3.99, -1.06, 0.52, C.gray, 2);
  line(s, 7.05, 3.99, 1.06, 0.52, C.gray, 2);
  rect(s, 0.62, 5.94, 12.04, 0.35, C.amberBg, 'E6C45C');
  addText(s, '63 SYNTHETIC FALSE NEGATIVES', 0.85, 6.02, 2.52, 0.18, 8.7, C.orange, true, { charSpacing: 0.55 });
  addText(s, 'at the current 0.5 cutoff — model evidence for burden analysis, not a field failure rate.', 3.42, 6.0, 8.82, 0.21, 9.6, C.ink, true);
  boundaryStrip(s);
  source(s, 'Sources: simulator/coordinator.py; stored synthetic model metrics; report ethics canvas and burden register.');
  notes(s, [
    'Report benefit and burden together. No amount of aggregate savings should hide severe local discomfort or unacceptable missed-risk burden.',
    'The 63 false negatives come from a 480-row synthetic holdout at cutoff 0.5; they are not field failures or a real facility risk rate.',
    'Real-world fairness, accessibility, operator workload, privacy impact, and comfort burden remain target evidence.'
  ]);
}

// Slide 7 — bounded authority
{
  const s = pptx.addSlide('MASTER');
  title(s, 'Ethical safety · Human authority', 'ROI cannot buy permission to automate.', 'Human review is the default; every increase in authority requires a separate evidence gate, explicit stop rule, and rollback proof.');
  claimType(s, 'current', 0.62, 1.86, 1.87);
  const stages = [
    { x: 0.62, y: 4.42, name: 'SIMULATION', sub: 'Manual review', tag: 'CURRENT', color: C.blue, fill: C.blueBg },
    { x: 3.15, y: 3.85, name: 'READ-ONLY SHADOW', sub: 'Observe; no control', tag: 'PILOT TARGET', color: C.green, fill: C.tealBg },
    { x: 5.68, y: 3.28, name: 'HUMAN-REVIEWED ALERTS', sub: 'Approve / reject', tag: 'FUTURE GATE', color: C.orange, fill: C.amberBg },
    { x: 8.21, y: 2.71, name: 'BOUNDED AUTOMATION', sub: 'Only after signed gates', tag: 'FUTURE GATE', color: C.purple, fill: C.purpleBg }
  ];
  stages.forEach((a, i) => {
    rect(s, a.x, a.y, 2.22, 1.22, a.fill, a.color);
    addText(s, a.tag, a.x + 0.16, a.y + 0.15, 1.9, 0.21, 8.1, a.color, true, { align: 'center', charSpacing: 0.7 });
    addText(s, a.name, a.x + 0.16, a.y + 0.47, 1.9, 0.31, 11, C.ink, true, { align: 'center' });
    addText(s, a.sub, a.x + 0.16, a.y + 0.86, 1.9, 0.2, 8.8, C.muted, true, { align: 'center' });
    if (i < 3) line(s, a.x + 2.22, a.y + 0.6, 0.35, -0.57, C.gray, 1.5, 'solid', undefined, 'triangle');
  });
  rect(s, 10.74, 2.15, 1.92, 3.5, C.redBg, 'E89993');
  addText(s, 'NOT AUTHORIZED', 10.94, 2.44, 1.52, 0.28, 9, C.red, true, { align: 'center', charSpacing: 0.7 });
  addText(s, 'Physical\nautonomy', 10.94, 3.0, 1.52, 0.64, 19, C.ink, true, { align: 'center' });
  line(s, 11.15, 3.92, 1.1, 0, C.red, 3);
  addText(s, 'Requires a separate deployment decision and complete security, safety, ethics, and recovery evidence.', 10.96, 4.2, 1.48, 0.9, 9.5, C.muted, true, { align: 'center' });
  rect(s, 0.62, 5.9, 9.75, 0.39, C.dark, C.dark);
  addText(s, 'Favorable ROI ≠ minimum ventilation  ·  Encryption ≠ authorization  ·  Accuracy ≠ acceptable false negatives', 0.84, 5.99, 9.31, 0.19, 9.2, C.white, true, { align: 'center' });
  boundaryStrip(s);
  source(s, 'Sources: simulator/ecosystem.py and knowledge_base.py; report decision-rights matrix and governance gates.');
  notes(s, [
    'Current auto-action mode is explicit opt-in and mutates simulated state only. Manual review remains the normal operating position.',
    'The four 15-tick heuristic checks are software evaluation aids, not safety certification or facility approval.',
    'Do not imply a named approver, signed authority, physical stop, automatic work order, or permission for real-equipment autonomy.'
  ]);
}

// Slide 8 — executive ask
{
  const s = pptx.addSlide('MASTER');
  title(s, 'Decision ask', 'Approve an evidence-hardening pilot—not production deployment.', 'Three workstreams replace assumptions with evidence and end in an explicit advance, redesign, or stop decision.');
  claimType(s, 'target', 0.62, 1.86, 1.7);
  const work = [
    { x: 0.62, n: '01', head: 'ROI EVIDENCE', color: C.orange, fill: C.amberBg, items: ['Normalize the energy baseline', 'Validate tariff, incidents and costs', 'Pre-register measurement method'] },
    { x: 4.42, n: '02', head: 'SECURITY EVIDENCE', color: C.blue, fill: C.blueBg, items: ['Implement identity, TLS/WSS and ACLs', 'Test freshness, authorization and audit', 'Exercise isolation, fallback and recovery'] },
    { x: 8.22, n: '03', head: 'ETHICAL-SAFETY EVIDENCE', color: C.green, fill: C.tealBg, items: ['Set comfort and starvation limits', 'Set workload, false-negative and privacy rules', 'Name stop authority and rollback criteria'] }
  ];
  work.forEach((a) => {
    rect(s, a.x, 2.3, 3.52, 2.55, a.fill, a.color);
    numberCircle(s, a.n, a.x + 0.25, 2.55, a.color);
    addText(s, a.head, a.x + 0.85, 2.56, 2.35, 0.28, 10.5, a.color, true, { charSpacing: 0.7 });
    line(s, a.x + 0.25, 3.18, 3.0, 0, C.white, 1);
    a.items.forEach((t, i) => {
      dot(s, a.x + 0.28, 3.5 + i * 0.44, 0.13, a.color);
      addText(s, t, a.x + 0.58, 3.39 + i * 0.44, 2.57, 0.29, 10.5, C.ink, true);
    });
  });
  rect(s, 0.62, 5.14, 12.04, 1.16, C.dark, C.dark);
  addText(s, 'PILOT OUTPUT', 0.92, 5.33, 1.55, 0.24, 9, C.green, true, { charSpacing: 1 });
  addText(s, 'ADVANCE TO READ-ONLY SHADOW', 2.75, 5.28, 3.0, 0.34, 15, C.white, true, { align: 'center' });
  addText(s, 'OR', 5.75, 5.3, 0.5, 0.3, 11, C.steel, true, { align: 'center' });
  addText(s, 'REDESIGN', 6.25, 5.28, 1.75, 0.34, 15, C.orange, true, { align: 'center' });
  addText(s, 'OR', 8.0, 5.3, 0.5, 0.3, 11, C.steel, true, { align: 'center' });
  addText(s, 'STOP', 8.52, 5.28, 1.3, 0.34, 15, C.red, true, { align: 'center' });
  pill(s, '161 SOFTWARE TESTS PASS', 10.2, 5.31, 2.06, C.blue, C.white, C.blue);
  addText(s, 'Prototype software evidence only — not field validation, safety certification, production security, or approval.', 2.75, 5.78, 7.06, 0.22, 8.8, C.steel, true, { align: 'center' });
  boundaryStrip(s);
  source(s, 'Sources: release-evidence/project2/tests; current ROI, security and governance evidence gaps.');
  notes(s, [
    'Ask for a governed evidence-hardening and read-only pilot. Do not ask for or imply production connectivity, physical control, or autonomous operation.',
    'Do not invent a funding amount, schedule, named owner, approver, signature, or deployment authorization.',
    'The current checkout has archived evidence for 161 passing software tests. That supports prototype software quality only.'
  ]);
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  await pptx.writeFile({ fileName: PPTX, compression: true });
  const sha = crypto.createHash('sha256').update(fs.readFileSync(PPTX)).digest('hex');
  console.log(JSON.stringify({ pptx: PPTX, slides: pptx._slides.length, sha256: sha }, null, 2));
})().catch((e) => { console.error(e); process.exit(1); });
