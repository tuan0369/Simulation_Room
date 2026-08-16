#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const out = path.join(__dirname, 'EcoHVAC_Guardian_Project2_Pitch.html');
const pdf = path.join(__dirname, 'EcoHVAC_Guardian_Project2_Pitch.pdf');
const chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
function dataUri(file) {
  return `data:image/png;base64,${fs.readFileSync(file).toString('base64')}`;
}
const operationsUi = dataUri(path.join(__dirname, '..', 'images', '01_operations_centre_dashboard.png'));
const predictiveUi = dataUri(path.join(__dirname, '..', 'images', '02_predictive_intelligence_hub.png'));
const spatialUi = dataUri(path.join(__dirname, '..', 'images', '07_3d_digital_twin_fullscreen.png'));
const html = String.raw`<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>EcoHVAC Guardian Project 2 Pitch</title>
<style>
@page { size: 13.333in 7.5in; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #dfe4e9; color: #172033; font-family: Arial, Helvetica, sans-serif; print-color-adjust: exact; -webkit-print-color-adjust: exact; }
.slide { position: relative; width: 13.333in; height: 7.5in; padding: .33in .62in .48in; overflow: hidden; background: #fff; page-break-after: always; break-after: page; }
.slide:last-child { page-break-after: auto; }
.kicker { color: #2166a5; font-size: 9pt; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; margin-bottom: .12in; }
h1 { color: #0b1f3a; font-size: 28pt; line-height: 1.08; letter-spacing: -.025em; margin: 0; max-width: 11.9in; }
.sub { margin-top: .13in; color: #5e6a7d; font-size: 11.5pt; line-height: 1.3; max-width: 11.7in; }
.title-rule { border-top: 1px solid #dde3ea; margin-top: .17in; }
.footer { position: absolute; left: .62in; right: .62in; bottom: .19in; border-top: 1px solid #dde3ea; padding-top: .07in; color: #8792a3; font-size: 6.6pt; letter-spacing: .06em; display: flex; justify-content: space-between; align-items: center; }
.source { position: absolute; right: .62in; bottom: .43in; color: #8792a3; font-size: 6.6pt; }
.row { display: flex; }
.card { border: 1px solid #dde3ea; border-radius: 8px; background: #fff; }
.pill { display: inline-flex; align-items: center; justify-content: center; min-height: .3in; padding: 0 .14in; border-radius: .15in; font-size: 8.2pt; font-weight: 700; letter-spacing: .07em; }
.blue { color:#2166a5; } .green { color:#14866d; } .orange { color:#d97706; } .red { color:#b42318; } .purple { color:#6e56cf; }
.bg-blue { background:#eaf2f8; } .bg-green { background:#e8f5f1; } .bg-amber { background:#fff4d6; } .bg-red { background:#fdecea; } .bg-purple { background:#f1eefb; }
.dot { width:.14in; height:.14in; border-radius:50%; flex:0 0 auto; }
.eyebrow { font-size: 9pt; font-weight: 700; letter-spacing: .09em; }
.muted { color:#5e6a7d; }
.center { text-align:center; }
.ui-frame { overflow:hidden; border:1px solid #c8d3df; border-radius:10px; background:#eef2f6; box-shadow:0 12px 28px rgba(11,31,58,.13); }
.ui-frame img { width:100%; height:100%; object-fit:cover; display:block; }
.evidence-tag { position:absolute; z-index:4; padding:.07in .13in; border-radius:.14in; background:#fff; border:1px solid #c8d3df; color:#0b1f3a; font-size:8pt; font-weight:700; box-shadow:0 5px 14px rgba(11,31,58,.13); }
.twin-proof { display:grid; grid-template-columns:7.45in 4.25in; gap:.38in; margin-top:.28in; }
.twin-ui { position:relative; height:4.25in; }
.twin-ui img { object-position:center 42%; }
.proof-stack { display:flex; flex-direction:column; gap:.14in; }
.proof-card { min-height:.92in; padding:.16in .2in; border-left:4px solid currentColor; }
.proof-card .head { font-size:9pt; font-weight:700; letter-spacing:.07em; }
.proof-card .copy { margin-top:.06in; color:#172033; font-size:11pt; line-height:1.25; font-weight:700; }
.loop-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:.26in; margin-top:.3in; }
.loop-step { position:relative; min-height:1.17in; padding:.18in .16in; text-align:center; border:1px solid currentColor; border-radius:8px; }
.loop-step:not(:last-child):after { content:"→"; position:absolute; right:-.23in; top:.38in; color:#8792a3; font-size:15pt; font-weight:700; }
.loop-step .num { font-size:8pt; font-weight:700; letter-spacing:.07em; }
.loop-step .head { margin-top:.07in; font-size:11pt; font-weight:700; }
.loop-step .copy { margin-top:.05in; color:#5e6a7d; font-size:8.4pt; line-height:1.2; }
.causal { display:grid; grid-template-columns:repeat(4,1fr); gap:.24in; margin-top:.34in; }
.causal-card { min-height:2.05in; padding:.22in .2in; border:1px solid currentColor; border-radius:8px; }
.causal-card .tag { font-size:8.5pt; font-weight:700; letter-spacing:.08em; }
.causal-card .big { margin-top:.18in; font-size:22pt; font-weight:700; }
.causal-card .copy { margin-top:.11in; color:#172033; font-size:10.5pt; font-weight:700; line-height:1.3; }
.causal-card .detail { margin-top:.09in; color:#5e6a7d; font-size:8.8pt; line-height:1.25; }
.pred-layout { display:grid; grid-template-columns:7.65in 4.02in; gap:.35in; margin-top:.28in; }
.pred-ui { height:4.28in; }
.pred-ui img { object-position:center 39%; }
.pred-side { display:flex; flex-direction:column; gap:.14in; }
.pred-metric { padding:.16in .18in; min-height:.83in; }
.pred-metric strong { font-size:17pt; display:block; }
.pred-metric span { display:block; color:#5e6a7d; font-size:8.5pt; margin-top:.04in; line-height:1.2; }
.roi-compact { display:grid; grid-template-columns:4.35in 3.7in 3.7in; gap:.28in; margin-top:.35in; }
.roi-equation { min-height:3.3in; padding:.3in; }
.roi-equation .total { font-size:29pt; color:#2166a5; font-weight:700; margin:.2in 0 .08in; }
.roi-line { display:flex; justify-content:space-between; padding:.12in 0; border-bottom:1px solid #dde3ea; font-size:11pt; font-weight:700; }
.range-card { min-height:3.3in; padding:.28in; }
.range-row { display:grid; grid-template-columns:.7in 1.2in 1fr; align-items:center; padding:.18in 0; border-bottom:1px solid #dde3ea; }
.range-row:last-child { border:0; }
.range-row .case { font-size:8.5pt; font-weight:700; letter-spacing:.06em; }
.range-row .val { font-size:14pt; font-weight:700; }
.range-row .pay { font-size:9pt; color:#5e6a7d; text-align:right; }
.gate-card { min-height:3.3in; padding:.28in; background:#0b1f3a; color:#fff; }
.gate-card .head { color:#14866d; font-size:9pt; font-weight:700; letter-spacing:.08em; }
.gate-card h2 { font-size:19pt; line-height:1.15; margin:.18in 0; }
.gate-card li { color:#cbd5e1; font-size:10.5pt; margin:.13in 0; line-height:1.25; }

/* cover */
.cover { background:#09182b; color:#fff; padding:.56in .74in; }
.cover:after { content:""; position:absolute; width:5.3in; height:5.3in; border-radius:50%; right:-1.3in; top:-1.55in; border:.18in solid rgba(78,140,201,.54); background:rgba(20,41,68,.55); }
.cover .badge { position:relative; z-index:2; background:#2166a5; padding:.08in .17in; border-radius:.16in; display:inline-block; font-size:8.4pt; font-weight:700; letter-spacing:.08em; }
.cover h1 { position:relative; z-index:2; margin-top:.36in; color:#fff; font-size:31pt; line-height:1.1; width:7.1in; }
.cover .lead { position:relative; z-index:2; margin-top:.22in; width:6.7in; color:#b8c4d3; font-size:15pt; line-height:1.35; }
.thesis { position:absolute; z-index:3; left:8in; top:1.25in; width:4.35in; height:3.8in; border:1px solid #29405f; border-radius:8px; background:#142944; padding:.35in .38in; }
.thesis-title { color:#14866d; font-size:9pt; font-weight:700; letter-spacing:.12em; margin-bottom:.22in; }
.thesis-item { display:grid; grid-template-columns:.42in .82in 1fr; gap:.12in; align-items:start; padding:.13in 0 .18in; border-bottom:1px solid #29405f; }
.thesis-item:last-child { border:0; }
.thesis-num { font-size:11pt; font-weight:700; }
.thesis-label { font-size:8.5pt; font-weight:700; letter-spacing:.08em; }
.thesis-copy { color:#fff; font-size:11.5pt; font-weight:700; line-height:1.25; }
.recommend { position:absolute; z-index:3; left:.74in; top:5.25in; width:11.61in; height:.72in; border:1px solid #29405f; border-radius:8px; background:#142944; display:flex; align-items:center; padding:0 .25in; }
.recommend .label { width:1.5in; color:#d97706; font-size:9pt; font-weight:700; letter-spacing:.07em; }
.recommend .copy { color:#fff; font-size:14pt; font-weight:700; }
.scope { position:absolute; left:.74in; top:6.34in; color:#9fb0c6; font-size:8.8pt; }
.cover .footer { border-color:#29405f; color:#9fb0c6; }
.cover .source { color:#9fb0c6; }

/* slide 2 */
.equation { display:grid; grid-template-columns:2.3in .5in 2.65in .5in 2.3in .5in 2.85in; align-items:center; margin-top:.5in; }
.eq-card { height:1.48in; border:1px solid currentColor; border-radius:8px; display:flex; flex-direction:column; justify-content:center; align-items:center; }
.eq-value { font-size:26pt; font-weight:700; }
.eq-label { margin-top:.11in; color:#5e6a7d; font-size:8.8pt; font-weight:700; letter-spacing:.06em; }
.op { font-size:24pt; font-weight:700; color:#8792a3; text-align:center; }
.value-row { display:grid; grid-template-columns:7.6in 1.85in 2in; gap:.32in; margin-top:.38in; }
.driver { height:1.32in; padding:.24in .3in; }
.driver-top { display:flex; align-items:center; gap:.18in; }
.driver-big { font-size:28pt; font-weight:700; color:#d97706; }
.driver-copy { font-size:16pt; line-height:1.2; font-weight:700; }
.bar { height:.07in; margin-top:.18in; background:#dde3ea; border-radius:4px; overflow:hidden; }
.bar span { display:block; height:100%; width:92%; background:#d97706; }
.metric { height:1.32in; display:flex; flex-direction:column; justify-content:center; align-items:center; }
.metric strong { font-size:22pt; }
.metric span { font-size:8.8pt; color:#5e6a7d; font-weight:700; letter-spacing:.05em; margin-top:.08in; }
.implication { margin-top:.22in; display:flex; gap:.22in; align-items:center; }
.implication b:first-child { color:#2166a5; font-size:9pt; letter-spacing:.07em; }
.implication b:last-child { color:#0b1f3a; font-size:13pt; }

/* slide 3 */
.scenarios { display:grid; grid-template-columns:2.92in 2.92in 2.92in 1.82in; gap:.49in; margin-top:.35in; }
.scenario { height:2.05in; border:1px solid currentColor; border-radius:8px; padding:.26in .18in; text-align:center; }
.scenario .name { font-size:9pt; font-weight:700; letter-spacing:.09em; }
.scenario .value { font-size:25pt; font-weight:700; margin-top:.23in; }
.scenario .desc { color:#5e6a7d; font-size:8.6pt; margin-top:.05in; }
.scenario .pay { font-size:11.5pt; font-weight:700; margin-top:.15in; }
.uncertainty { height:2.05in; border:1px solid #e6c45c; border-radius:8px; text-align:center; padding:.28in .12in; }
.uncertainty .name { color:#9a6700; font-size:9pt; line-height:1.3; font-weight:700; letter-spacing:.07em; }
.uncertainty .value { font-size:18pt; font-weight:700; margin-top:.18in; }
.proof-title { margin-top:.46in; font-size:10.5pt; font-weight:700; color:#0b1f3a; letter-spacing:.07em; }
.proof-grid { display:grid; grid-template-columns:1fr 1fr; column-gap:.56in; row-gap:.18in; margin-top:.19in; }
.proof { display:grid; grid-template-columns:.38in 1.55in 1fr; gap:.1in; align-items:start; }
.proof .n { color:#2166a5; font-size:10pt; font-weight:700; }
.proof .head { color:#2166a5; font-size:8.8pt; font-weight:700; letter-spacing:.05em; }
.proof .copy { font-size:10.5pt; font-weight:700; line-height:1.22; }

/* slide 4 */
.chain { display:grid; grid-template-columns:repeat(4, 1fr); gap:.38in; margin-top:.38in; }
.chain-card { position:relative; height:2.04in; border:1px solid currentColor; border-radius:8px; padding:.24in .2in; }
.chain-card:not(:last-child):after { content:"→"; position:absolute; right:-.32in; top:.72in; color:#8792a3; font-size:18pt; font-weight:700; }
.chain-top { display:flex; gap:.18in; align-items:center; }
.chain-num { font-size:17pt; font-weight:700; }
.chain-head { font-size:10pt; font-weight:700; letter-spacing:.08em; }
.chain-copy { border-top:1px solid #fff; margin-top:.17in; padding-top:.2in; text-align:center; font-size:13pt; font-weight:700; line-height:1.25; }
.outcomes-title { margin-top:.44in; font-size:10.5pt; font-weight:700; color:#0b1f3a; letter-spacing:.08em; }
.outcomes { display:grid; grid-template-columns:repeat(4, 1fr); gap:.3in; margin-top:.18in; }
.outcome { height:.88in; padding:.16in .2in; display:grid; grid-template-columns:.14in 1fr; column-gap:.14in; align-items:center; }
.outcome strong { display:block; font-size:10.5pt; }
.outcome span { display:block; margin-top:.06in; color:#5e6a7d; font-size:8.7pt; }
.proof-note { margin-top:.24in; color:#5e6a7d; font-size:9.5pt; }

/* slide 5 */
.ledger { display:grid; grid-template-columns:5.35in 1.38in 5.31in; gap:0; margin-top:.35in; align-items:center; }
.ledger-card { height:3.45in; border:1px solid currentColor; border-radius:8px; padding:.3in .32in; }
.ledger-title { font-size:10.5pt; font-weight:700; letter-spacing:.1em; margin-bottom:.26in; }
.ledger-row { display:grid; grid-template-columns:.14in 1.25in 1fr; gap:.17in; align-items:center; height:.56in; }
.ledger-row strong { font-size:11pt; }
.ledger-row span { color:#5e6a7d; font-size:10.5pt; }
.ledger-mid { width:1.38in; height:1.38in; border-radius:50%; background:#0b1f3a; color:#fff; display:flex; align-items:center; justify-content:center; text-align:center; font-size:13pt; font-weight:700; line-height:1.25; }
.signal { margin-top:.32in; height:.46in; border:1px solid #e6c45c; border-radius:8px; display:flex; align-items:center; padding:0 .25in; }
.signal .label { color:#d97706; font-size:8.8pt; font-weight:700; letter-spacing:.07em; width:2.1in; }
.signal .copy { font-size:10.5pt; font-weight:700; }

/* slide 6 */
.authority { position:relative; height:3.75in; margin-top:.24in; }
.step { position:absolute; width:2.28in; height:1.3in; border:1px solid currentColor; border-radius:8px; text-align:center; padding:.14in .16in; }
.step .tag { font-size:8.2pt; font-weight:700; letter-spacing:.07em; }
.step .name { margin-top:.11in; font-size:15pt; font-weight:700; color:#172033; }
.step .copy { margin-top:.09in; color:#5e6a7d; font-size:9pt; font-weight:700; }
.step1 { left:0; top:2.2in; } .step2 { left:2.6in; top:1.6in; } .step3 { left:5.2in; top:1in; } .step4 { left:7.8in; top:.4in; }
.step:not(.step4):after { content:"↗"; position:absolute; right:-.31in; top:.31in; font-size:19pt; color:#8792a3; }
.requires { position:absolute; right:0; top:0; width:1.68in; height:3.5in; padding:.28in .2in; }
.requires .head { color:#2166a5; font-size:9pt; font-weight:700; text-align:center; letter-spacing:.07em; line-height:1.25; }
.requires ul { list-style:none; padding:0; margin:.25in 0 0; }
.requires li { position:relative; font-size:9.2pt; font-weight:700; margin:.17in 0; padding-left:.25in; line-height:1.2; }
.requires li:before { content:""; position:absolute; left:0; top:.06in; width:.13in; height:.13in; border-radius:50%; background:#2166a5; }
.boundary { margin-top:.04in; display:grid; grid-template-columns:2.9in 1fr; gap:.18in; align-items:start; }
.boundary .head { font-size:9.5pt; font-weight:700; color:#0b1f3a; letter-spacing:.07em; }
.boundary .copy { font-size:11.2pt; font-weight:700; line-height:1.25; }

/* slide 7 */
.security { display:grid; grid-template-columns:5.4in .55in 5.26in; gap:.34in; margin-top:.28in; align-items:center; }
.security-col { height:3.9in; }
.security-head { margin-bottom:.15in; }
.security-row { display:grid; grid-template-columns:2.1in 1fr; gap:.14in; min-height:.62in; align-items:start; padding:.12in 0; border-bottom:1px solid #dde3ea; }
.security-row:last-child { border:0; }
.security-row strong { font-size:10.5pt; }
.security-row span { color:#5e6a7d; font-size:9.8pt; line-height:1.2; }
.security-arrow { text-align:center; color:#8792a3; font-size:25pt; font-weight:700; }
.decision-rule { height:.48in; border-radius:8px; background:#0b1f3a; color:#fff; display:flex; align-items:center; padding:0 .28in; margin-top:.06in; }
.decision-rule .label { color:#14866d; font-size:8.8pt; font-weight:700; letter-spacing:.07em; width:1.4in; }
.decision-rule .copy { font-size:12pt; font-weight:700; }

/* slide 8 */
.workstreams { display:grid; grid-template-columns:repeat(3, 1fr); gap:.28in; margin-top:.34in; }
.work { height:2.62in; border:1px solid currentColor; border-radius:8px; padding:.27in .25in; }
.work-head { display:grid; grid-template-columns:.43in 1fr; gap:.18in; align-items:center; }
.work-num { width:.43in; height:.43in; border-radius:50%; color:#fff; display:flex; align-items:center; justify-content:center; font-size:11pt; font-weight:700; }
.work-title { font-size:11pt; font-weight:700; letter-spacing:.08em; }
.work ul { border-top:1px solid #fff; list-style:none; margin:.25in 0 0; padding:.18in 0 0; }
.work li { position:relative; font-size:10.5pt; font-weight:700; margin:.16in 0; padding-left:.3in; }
.work li:before { content:""; position:absolute; left:0; top:.04in; width:.13in; height:.13in; border-radius:50%; background:currentColor; }
.exit-title { margin-top:.38in; font-size:10pt; font-weight:700; color:#0b1f3a; letter-spacing:.07em; }
.exit { display:grid; grid-template-columns:repeat(3, 1fr); gap:.35in; margin-top:.15in; }
.exit-card { height:.74in; border:1px solid currentColor; border-radius:8px; display:grid; grid-template-columns:1.2in 1fr; align-items:center; padding:0 .18in; }
.exit-card strong { font-size:13pt; text-align:center; }
.exit-card span { color:#172033; font-size:9.5pt; font-weight:700; text-align:center; }
.foundation { text-align:center; color:#5e6a7d; font-size:8.8pt; margin-top:.15in; }

/* business-first trust and future */
.trust-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:.25in; margin-top:.3in; }
.trust-card { min-height:3.55in; padding:.25in .24in; }
.trust-card .head { font-size:10pt; font-weight:700; letter-spacing:.08em; }
.trust-card .claim { margin-top:.12in; font-size:13pt; line-height:1.25; font-weight:700; }
.trust-card ul { list-style:none; padding:0; margin:.2in 0 0; }
.trust-card li { position:relative; padding:.11in 0 .11in .24in; border-top:1px solid rgba(23,32,51,.12); font-size:9.3pt; line-height:1.25; }
.trust-card li:before { content:""; position:absolute; left:0; top:.17in; width:.1in; height:.1in; border-radius:50%; background:currentColor; }
.roadmap { display:grid; grid-template-columns:repeat(5,1fr); gap:.25in; margin-top:.42in; }
.road-step { position:relative; min-height:2.4in; padding:.22in .18in; border:1px solid currentColor; border-radius:8px; }
.road-step:not(:last-child):after { content:"→"; position:absolute; right:-.22in; top:.88in; color:#8792a3; font-size:15pt; font-weight:700; }
.road-step .stage { font-size:8pt; font-weight:700; letter-spacing:.08em; }
.road-step .name { margin-top:.13in; color:#172033; font-size:16pt; font-weight:700; }
.road-step .copy { margin-top:.14in; color:#5e6a7d; font-size:9.2pt; line-height:1.3; }
.road-step .gate { position:absolute; left:.18in; right:.18in; bottom:.17in; border-top:1px solid currentColor; padding-top:.11in; font-size:7.8pt; font-weight:700; line-height:1.2; }
.future-rule { margin-top:.3in; min-height:.74in; padding:.16in .23in; display:grid; grid-template-columns:1.55in 1fr; gap:.18in; align-items:center; }
.future-rule .label { font-size:8.5pt; font-weight:700; letter-spacing:.08em; }
.future-rule .copy { font-size:11.2pt; line-height:1.25; font-weight:700; }

@media print { html, body { background:#fff; } }
</style>
</head>
<body>

<section class="slide cover">
  <div class="badge">EXECUTIVE PITCH</div>
  <h1>Turn shared HVAC from a hidden trade-off into a visible, governable business decision.</h1>
  <div class="lead">EcoHVAC Guardian helps decision-makers test how intelligent coordination could improve occupant comfort, reduce disruption and create measurable value—before increasing operational authority.</div>
  <div class="thesis">
    <div class="thesis-title">THE OPPORTUNITY</div>
    <div class="thesis-item"><div class="thesis-num orange">01</div><div class="thesis-label orange">VALUE</div><div class="thesis-copy">Focus investment on measurable energy and reliability outcomes</div></div>
    <div class="thesis-item"><div class="thesis-num green">02</div><div class="thesis-label green">PEOPLE</div><div class="thesis-copy">Make comfort and service fairness visible</div></div>
    <div class="thesis-item"><div class="thesis-num blue">03</div><div class="thesis-label blue">TRUST</div><div class="thesis-copy">Expand capability only as evidence and safeguards mature</div></div>
  </div>
  <div class="recommend"><div class="label">Recommendation</div><div class="copy">Use a governed evidence pilot to validate value, protect people and earn the next stage.</div></div>
  <div class="scope">EcoHVAC Guardian &nbsp;·&nbsp; Multi-room Digital Twin for shared HVAC intelligence</div>
  <div class="source">Pitch scope: classroom simulation and illustrative business case; deployment remains evidence-gated.</div>
  <div class="footer"><span>ECOHVAC GUARDIAN &nbsp;|&nbsp; EXECUTIVE PITCH</span><span>1</span></div>
</section>

<section class="slide">
  <div class="kicker">Business problem</div>
  <h1>A shared AHU turns separate room demands into one comfort, reliability and cost decision.</h1>
  <div class="sub">When capacity is constrained, local room requests create cross-zone consequences that conventional dashboards can leave hidden.</div>
  <div class="title-rule"></div>
  <div class="twin-proof">
    <div class="ui-frame twin-ui">
      <img src="${spatialUi}" alt="Four-room Three.js Digital Twin with a shared AHU">
      <div class="evidence-tag" style="left:.16in;top:.16in">CURRENT FOUR-ROOM UI</div>
      <div class="evidence-tag" style="right:.16in;bottom:.16in">LIVE SPATIAL STATE</div>
    </div>
    <div class="proof-stack">
      <div class="card proof-card blue bg-blue"><div class="head">COMFORT</div><div class="copy">Which occupied rooms receive scarce airflow?</div></div>
      <div class="card proof-card purple bg-purple"><div class="head">RELIABILITY</div><div class="copy">Can degradation and future risk be surfaced early?</div></div>
      <div class="card proof-card orange bg-amber"><div class="head">COST</div><div class="copy">Can avoidable energy and disruption be reduced?</div></div>
      <div class="card proof-card green bg-green"><div class="head">BUSINESS NEED</div><div class="copy">One decision view across four room twins and one 0.24 m³/s AHU</div></div>
    </div>
  </div>
  <div class="source">UI evidence: current four-room Three.js state view. It represents simulated assets, not a connected physical building.</div>
  <div class="footer"><span>ECOHVAC GUARDIAN &nbsp;|&nbsp; DIGITAL TWIN, VALUE & RESPONSIBLE INTELLIGENCE</span><span>2</span></div>
</section>

<section class="slide">
  <div class="kicker">Business hypothesis</div>
  <h1>The modeled value case lives or dies on avoided incidents—not energy savings alone.</h1>
  <div class="sub">The commercial opportunity is visible, but the range from no payback to 8.1 months makes incident evidence the pilot’s first management question.</div>
  <div class="title-rule"></div>
  <div class="roi-compact">
    <div class="card roi-equation">
      <span class="pill bg-amber" style="color:#9a6700;border:1px solid #e6c45c">ILLUSTRATIVE BASE CASE</span>
      <div class="total">S$9,080/year</div>
      <div class="muted" style="font-size:9pt;margin-bottom:.12in">Annual net value · 33.04-month payback</div>
      <div class="roi-line"><span>Energy value</span><span class="green">+ S$1,080</span></div>
      <div class="roi-line"><span>Avoided incidents</span><span class="orange">+ S$12,000</span></div>
      <div class="roi-line"><span>Annual support</span><span class="red">− S$4,000</span></div>
    </div>
    <div class="card range-card">
      <div class="eyebrow blue">SENSITIVITY</div>
      <div class="range-row"><span class="case red">LOW</span><span class="val red">−S$1,600</span><span class="pay">No payback</span></div>
      <div class="range-row"><span class="case blue">BASE</span><span class="val blue">S$9,080</span><span class="pay">33.0 months</span></div>
      <div class="range-row"><span class="case green">HIGH</span><span class="val green">S$29,625</span><span class="pay">8.1 months</span></div>
      <div style="margin-top:.18in;font-size:10pt;font-weight:700">≈92% of gross modeled benefit comes from avoided incidents.</div>
    </div>
    <div class="gate-card card">
      <div class="head">BUSINESS EVIDENCE GATE</div>
      <h2>Replace the key assumptions with measured evidence.</h2>
      <ul><li>Normalized HVAC energy baseline</li><li>Incident frequency, severity and avoidability</li><li>Applicable tariff and supplier costs</li><li>Comfort and operator-workload outcomes</li></ul>
    </div>
  </div>
  <div class="source">Editable illustrative scenarios—not measured savings, forecasts, quotations or an approved investment.</div>
  <div class="footer"><span>ECOHVAC GUARDIAN &nbsp;|&nbsp; DIGITAL TWIN, VALUE & RESPONSIBLE INTELLIGENCE</span><span>3</span></div>
</section>

<section class="slide">
  <div class="kicker">Digital Twin answer</div>
  <h1>The Digital Twin converts a shared constraint into a closed operating loop.</h1>
  <div class="sub">The interface is the window; the differentiator is persistent state that connects prediction, coordination, simulated response and verification.</div>
  <div class="title-rule"></div>
  <div class="ui-frame" style="height:3.12in;margin-top:.22in;position:relative">
    <img src="${operationsUi}" alt="EcoHVAC Digital Twin Operations Centre" style="object-position:center 57%">
    <div class="evidence-tag" style="left:.16in;top:.16in">CURRENT OPERATIONS CENTRE</div>
    <div class="evidence-tag" style="right:.16in;bottom:.16in">FOUR INSTANTIATED ROOM TWINS</div>
  </div>
  <div class="loop-grid">
    <div class="loop-step blue bg-blue"><div class="num">01</div><div class="head">MIRROR</div><div class="copy">Room, AHU, energy and risk state</div></div>
    <div class="loop-step purple bg-purple"><div class="num">02</div><div class="head">PREDICT</div><div class="copy">+5/+15-minute demand and fan risk</div></div>
    <div class="loop-step orange bg-amber"><div class="num">03</div><div class="head">COORDINATE</div><div class="copy">Rank requests with comfort-debt history</div></div>
    <div class="loop-step green bg-green"><div class="num">04</div><div class="head">RESPOND</div><div class="copy">Apply grants and physical-state updates</div></div>
    <div class="loop-step red bg-red"><div class="num">05</div><div class="head">VERIFY</div><div class="copy">Evaluate, acknowledge and retain authority</div></div>
  </div>
  <div class="source">Current UI/state evidence. Room 3/4 MQTT command/status plumbing is not yet symmetric with Rooms 1/2.</div>
  <div class="footer"><span>ECOHVAC GUARDIAN &nbsp;|&nbsp; DIGITAL TWIN, VALUE & RESPONSIBLE INTELLIGENCE</span><span>4</span></div>
</section>

<section class="slide">
  <div class="kicker">Function 1 · Coordinate and remember</div>
  <h1>The twin records what airflow was actually granted—not merely what each room requested.</h1>
  <div class="sub">An archived two-room integration trace shows causal allocation, actuator feedback and bounded memory of unmet service.</div>
  <div class="title-rule"></div>
  <div class="causal">
    <div class="causal-card blue bg-blue"><div class="tag">01 · COMMAND</div><div class="big">ACCEPTED</div><div class="copy">Stress scenario applied with correlated result</div><div class="detail">command_id: release-stress-001<br>accepted · changed · applied</div></div>
    <div class="causal-card purple bg-purple"><div class="tag">02 · CONSTRAINT</div><div class="big">0.320 → 0.095</div><div class="copy">Requested airflow exceeds degraded capacity</div><div class="detail">Room 1 grant: 0.0953 m³/s<br>Room 2 grant: 0.0000 m³/s</div></div>
    <div class="causal-card orange bg-amber"><div class="tag">03 · MEMORY</div><div class="big">6.00 → 24.12</div><div class="copy">Comfort debt records sustained unmet need</div><div class="detail">Limited service: 1 → 4 s<br>Future priority can reflect history</div></div>
    <div class="causal-card green bg-green"><div class="tag">04 · CONTROL</div><div class="big">PAUSE / RESET</div><div class="copy">Lifecycle commands create visible state transitions</div><div class="detail">Pause zeros instantaneous flow/power; baseline restores deterministic state</div></div>
  </div>
  <div class="card" style="margin-top:.28in;padding:.18in .24in;display:grid;grid-template-columns:2in 1fr;gap:.2in;align-items:center"><strong class="blue" style="font-size:9pt;letter-spacing:.07em">WHY THIS MATTERS</strong><span style="font-size:11.5pt;font-weight:700">Actual shared-resource grants feed back into room control—requested actuation is never assumed to have occurred.</span></div>
  <div class="source">Archived two-room MQTT integration trace; separate from the current four-room UI. Values rounded in headline.</div>
  <div class="footer"><span>ECOHVAC GUARDIAN &nbsp;|&nbsp; DIGITAL TWIN, VALUE & RESPONSIBLE INTELLIGENCE</span><span>5</span></div>
</section>

<section class="slide">
  <div class="kicker">Function 2 · Anticipate and verify</div>
  <h1>The twin projects what may happen next—and abstains outside supported inputs.</h1>
  <div class="sub">Thermal trajectories, equipment-risk evidence and post-action evaluation are connected to the same operating state.</div>
  <div class="title-rule"></div>
  <div class="pred-layout">
    <div class="ui-frame pred-ui" style="position:relative">
      <img src="${predictiveUi}" alt="Predictive Intelligence Hub with four-room trajectories and fan-risk evidence">
      <div class="evidence-tag" style="left:.16in;top:.16in">CURRENT PREDICTIVE UI</div>
      <div class="evidence-tag" style="right:.16in;bottom:.16in">FOUR-ROOM TRAJECTORIES</div>
    </div>
    <div class="pred-side">
      <div class="card pred-metric bg-blue"><strong class="blue">+5 / +15 min</strong><span>Interpretable continuation projections by room</span></div>
      <div class="card pred-metric bg-purple"><strong class="purple">OOD → ABSTAIN</strong><span>Missing, invalid or unsupported inputs do not become “low risk”</span></div>
      <div class="card pred-metric bg-green"><strong class="green">15 ticks</strong><span>Post-action checks for comfort, risk, energy and stability</span></div>
      <div class="card pred-metric bg-amber"><strong class="orange">161 tests</strong><span>Software evidence across control, fairness, energy, model and messaging</span></div>
    </div>
  </div>
  <div class="source">Fan-risk evidence uses synthetic training/holdout data; trajectories are deterministic teaching-model projections, not field forecasts.</div>
  <div class="footer"><span>ECOHVAC GUARDIAN &nbsp;|&nbsp; DIGITAL TWIN, VALUE & RESPONSIBLE INTELLIGENCE</span><span>6</span></div>
</section>

<section class="slide">
  <div class="kicker">Function 3 · Govern trust</div>
  <h1>Trust is an operating function: expose who waits, preserve human authority and secure every step.</h1>
  <div class="sub">The twin’s value depends on making burdens, decision rights and connection risks visible—not treating them as deployment footnotes.</div>
  <div class="title-rule"></div>
  <div class="trust-grid">
    <div class="card trust-card bg-green green"><div class="head">PEOPLE</div><div class="claim">Benefits and burdens share one ledger.</div><ul><li>Comfort deviation and denied-flow duration</li><li>Bounded comfort debt records unmet service history</li><li>Aggregate occupancy only—never identity or profiling</li><li>Missed-risk and operator-workload review</li></ul></div>
    <div class="card trust-card bg-blue blue"><div class="head">AUTHORITY</div><div class="claim">People retain high-impact decisions.</div><ul><li>Correlated application acknowledgement</li><li>Pause, resume and simulation emergency stop</li><li>Human approval or rejection of candidate policy</li><li>Named authority, stop rule and rollback before expansion</li></ul></div>
    <div class="card trust-card bg-purple purple"><div class="head">SECURITY</div><div class="claim">Connectivity must be earned.</div><ul><li>Current: strict validation, replay discipline, local audit option</li><li>Current broker: anonymous MQTT/WebSockets in plaintext</li><li>Before connection: identity, TLS/WSS and least privilege</li><li>Protected evidence, fallback and rehearsed recovery</li></ul></div>
  </div>
  <div class="source">Synthetic risk evidence is not a field failure rate; hardened broker controls are deployment targets, not current operating evidence.</div>
  <div class="footer"><span>ECOHVAC GUARDIAN &nbsp;|&nbsp; DIGITAL TWIN, VALUE & RESPONSIBLE INTELLIGENCE</span><span>7</span></div>
</section>

<section class="slide">
  <div class="kicker">Future potential</div>
  <h1>Operational authority can expand only as evidence, safeguards and accountability mature.</h1>
  <div class="sub">The Digital Twin creates a staged path from classroom simulation to separately governed site scale—without jumping directly to autonomy.</div>
  <div class="title-rule"></div>
  <div class="roadmap">
    <div class="road-step blue bg-blue"><div class="stage">CURRENT</div><div class="name">SIMULATE</div><div class="copy">Stress-test shared capacity, fairness, energy and risk in a repeatable environment.</div><div class="gate">FOUNDATION: SOFTWARE EVIDENCE</div></div>
    <div class="road-step green bg-green"><div class="stage">CONDITIONAL</div><div class="name">SHADOW</div><div class="copy">Ingest read-only facility telemetry and compare twin outputs with observed behavior.</div><div class="gate">GATE: DATA QUALITY + SECURITY</div></div>
    <div class="road-step orange bg-amber"><div class="stage">CONDITIONAL</div><div class="name">ADVISE</div><div class="copy">Offer human-reviewed comfort and maintenance recommendations with abstention.</div><div class="gate">GATE: FIELD MODEL + HUMAN IMPACT</div></div>
    <div class="road-step purple bg-purple"><div class="stage">CONDITIONAL</div><div class="name">CONTROL</div><div class="copy">Permit bounded, reversible low-consequence actions inside an approved safety envelope.</div><div class="gate">GATE: SAFETY + ROLLBACK + AUTHORITY</div></div>
    <div class="road-step red bg-red"><div class="stage">CONDITIONAL</div><div class="name">SCALE</div><div class="copy">Coordinate multiple AHUs or sites under separate governance and local fallback.</div><div class="gate">GATE: SITE-BY-SITE VALUE + TRUST</div></div>
  </div>
  <div class="card future-rule bg-blue"><div class="label blue">POTENTIAL VALUE</div><div class="copy">Move from understanding one shared asset to learning where predictive coordination creates repeatable value—while preserving local human control.</div></div>
  <div class="source">Future stages are proposed and evidence-gated; no schedule, budget, facility approval, physical autonomy or site-scale benefit is asserted.</div>
  <div class="footer"><span>ECOHVAC GUARDIAN &nbsp;|&nbsp; DIGITAL TWIN, VALUE & RESPONSIBLE INTELLIGENCE</span><span>8</span></div>
</section>

<section class="slide">
  <div class="kicker">Decision and next step</div>
  <h1>Approve an evidence-building pilot—not autonomous deployment.</h1>
  <div class="sub">Use the Digital Twin to prove value, protect people and earn the evidence required for read-only shadow operation.</div>
  <div class="title-rule"></div>
  <div class="workstreams">
    <div class="work bg-amber orange"><div class="work-head"><div class="work-num" style="background:#d97706">01</div><div class="work-title">PROVE VALUE</div></div><ul><li>Normalize energy baseline</li><li>Validate incident economics</li><li>Confirm full implementation cost</li></ul></div>
    <div class="work bg-green green"><div class="work-head"><div class="work-num" style="background:#14866d">02</div><div class="work-title">PROTECT PEOPLE</div></div><ul><li>Measure comfort and fairness</li><li>Review missed risk and abstention</li><li>Confirm purpose and privacy limits</li></ul></div>
    <div class="work bg-blue blue"><div class="work-head"><div class="work-num" style="background:#2166a5">03</div><div class="work-title">EARN TRUST</div></div><ul><li>Test identity and access</li><li>Demonstrate protected evidence</li><li>Rehearse fallback and recovery</li></ul></div>
  </div>
  <div class="exit-title">EVIDENCE-BASED EXIT</div>
  <div class="exit">
    <div class="exit-card bg-green green"><strong>ADVANCE</strong><span>to read-only shadow</span></div>
    <div class="exit-card bg-amber orange"><strong>REDESIGN</strong><span>if value or safeguards are weak</span></div>
    <div class="exit-card bg-red red"><strong>STOP</strong><span>if burdens cannot be bounded</span></div>
  </div>
  <div class="foundation">Current foundation: four-room simulation, one shared AHU, predictive intelligence, governed command lifecycle and 161 passing software tests.</div>
  <div class="source">Decision scope: classroom simulation pilot; no facility authorization, physical autonomy, budget, schedule or signatory is asserted.</div>
  <div class="footer"><span>ECOHVAC GUARDIAN &nbsp;|&nbsp; DIGITAL TWIN, VALUE & RESPONSIBLE INTELLIGENCE</span><span>9</span></div>
</section>

</body>
</html>`;
fs.writeFileSync(out, html);
execFileSync(chrome, [
  '--headless',
  '--disable-gpu',
  '--no-pdf-header-footer',
  `--print-to-pdf=${pdf}`,
  `file://${out}`,
], { stdio: 'inherit' });
console.log(JSON.stringify({ html: out, pdf, slides: 9 }, null, 2));
