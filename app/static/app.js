const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const pct = (x, digits = 0) => (x == null ? "n/a" : `${(x * 100).toFixed(digits)}%`);
const escapeHtml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function svg(tag, attrs = {}, parent) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (parent) parent.append(node);
  return node;
}

/* ---------- Tooltip ---------- */
const tooltip = $("tooltip");
function showTip(event, html) {
  tooltip.innerHTML = html;
  tooltip.hidden = false;
  const { width, height } = tooltip.getBoundingClientRect();
  const x = Math.min(event.clientX + 14, window.innerWidth - width - 8);
  const y = event.clientY - height - 12 < 8 ? event.clientY + 16 : event.clientY - height - 12;
  tooltip.style.left = `${Math.max(8, x)}px`;
  tooltip.style.top = `${y}px`;
}
const hideTip = () => (tooltip.hidden = true);
function tip(node, html) {
  node.addEventListener("pointermove", (event) => showTip(event, typeof html === "function" ? html() : html));
  node.addEventListener("pointerleave", hideTip);
}

/* ---------- Scope gauge ---------- */
const GAUGE_R = 166;
const gaugePoint = (t, r) => {
  const angle = ((135 + 270 * t) * Math.PI) / 180;
  return [200 + r * Math.cos(angle), 200 + r * Math.sin(angle)];
};
const ARC_LENGTH = 2 * Math.PI * GAUGE_R * 0.75;

function drawGauge() {
  const [x0, y0] = gaugePoint(0, GAUGE_R);
  const [x1, y1] = gaugePoint(1, GAUGE_R);
  const d = `M ${x0} ${y0} A ${GAUGE_R} ${GAUGE_R} 0 1 1 ${x1} ${y1}`;
  $("scope-track").setAttribute("d", d);
  const arc = $("scope-arc");
  arc.setAttribute("d", d);
  arc.style.setProperty("--arc-length", ARC_LENGTH);
  arc.style.strokeDasharray = ARC_LENGTH;
  arc.style.strokeDashoffset = ARC_LENGTH;
  for (let i = 0; i <= 10; i++) {
    const major = i % 5 === 0;
    const [a, b] = gaugePoint(i / 10, 176);
    const [c, e] = gaugePoint(i / 10, major ? 185 : 181);
    svg("line", { x1: a, y1: b, x2: c, y2: e, class: major ? "scope-tick scope-tick-major" : "scope-tick" }, $("scope-ticks"));
    if (major) {
      const [x, y] = gaugePoint(i / 10, 193);
      svg("text", { x, y, class: "scope-tick-label" }, $("scope-labels")).textContent = `${i * 10}`;
    }
  }
}
function setGauge(probability) {
  const scope = $("dropzone");
  scope.classList.remove("is-loading");
  scope.classList.toggle("is-malignant", probability != null && probability >= 0.5);
  $("scope-arc").style.strokeDashoffset = ARC_LENGTH * (1 - (probability ?? 0));
}

/* ---------- Check an image ---------- */
let lesionTypes = [];
const typeName = (value) => (value ?? "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

function showImage(url) {
  $("scope-image").setAttribute("href", url);
  $("scope-prompt").hidden = true;
}
function startLoading() {
  $("error").hidden = true;
  $("readout-empty").hidden = true;
  $("readout-result").hidden = true;
  $("dropzone").classList.remove("is-malignant");
  $("dropzone").classList.add("is-loading");
}
function showError(message) {
  setGauge(null);
  $("readout-result").hidden = true;
  $("readout-empty").hidden = false;
  $("error").textContent = message;
  $("error").hidden = false;
}

function showResult(result, truth) {
  const p = result.malignant_probability;
  setGauge(p);
  $("readout-empty").hidden = true;
  $("readout-result").hidden = false;

  if (p == null) {
    $("verdict").textContent = "The model declined to answer";
    $("probability-value").textContent = "";
    $("probability-label").textContent = "No malignancy probability was returned for this image.";
  } else {
    $("verdict").textContent = p >= 0.5 ? "Likely malignant" : "Likely benign";
    $("probability-value").textContent = pct(p);
    $("probability-label").textContent = "probability of malignancy";
  }

  const lesion = result.is_skin_lesion_probability;
  $("lesion-warning").hidden = !(lesion != null && lesion < 0.5);
  $("lesion-warning").textContent = `This may not be a skin lesion (${pct(lesion)} likely that it is), so treat the result with suspicion.`;

  const truthNode = $("truth");
  truthNode.hidden = !truth;
  if (truth) {
    const agrees = p != null && (p >= 0.5) === (truth.label === "malignant");
    truthNode.className = `truth ${agrees ? "agrees" : "disagrees"}`;
    const how = truth.confirmed_by ? `, confirmed by ${truth.confirmed_by}` : "";
    truthNode.textContent = `Confirmed diagnosis: ${truth.diagnosis} (${truth.label})${how}. The model ${agrees ? "agrees" : "got this one wrong"}.`;
  }

  const probabilities = result.lesion_type_probabilities ?? {};
  const rows = lesionTypes
    .map((t) => ({ ...t, probability: probabilities[t.value] ?? 0 }))
    .sort((a, b) => b.probability - a.probability)
    .filter((t, i) => i < 4 || t.probability >= 0.02);
  const list = $("types");
  list.replaceChildren();
  const hasTypes = Object.keys(probabilities).length > 0;
  list.previousElementSibling.hidden = !hasTypes;
  $("types-legend").hidden = !hasTypes;
  if (hasTypes) {
    rows.forEach((t, i) => {
      const item = document.createElement("li");
      item.className = `${t.malignant ? "is-malignant" : ""} ${i === 0 ? "is-top" : ""}`;
      item.innerHTML = `<span>${typeName(t.value)}</span><span class="bar"><span style="width:${t.probability * 100}%"></span></span><span class="value">${pct(t.probability)}</span>`;
      item.title = t.description;
      list.append(item);
    });
  }
  $("result-meta").textContent = `Answered in ${result.latency_ms} ms by ${result.model} through the Decisions API.`;
}

async function classify(request, truth) {
  startLoading();
  try {
    const response = await request;
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `The server returned ${response.status}.`);
    showResult(body, truth);
  } catch (error) {
    showError(error.message || "Could not reach the server.");
  }
}

function classifyFile(file) {
  if (!file) return;
  if (!file.type.startsWith("image/")) return showError("That file is not an image. Use a JPEG or PNG.");
  showImage(URL.createObjectURL(file));
  const form = new FormData();
  form.append("file", file);
  classify(fetch("/api/classify", { method: "POST", body: form }));
}

function setupCheck() {
  drawGauge();
  const zone = $("dropzone");
  $("choose").addEventListener("click", () => $("file").click());
  $("again").addEventListener("click", () => $("file").click());
  $("file").addEventListener("change", (event) => classifyFile(event.target.files[0]));
  ["dragenter", "dragover"].forEach((name) =>
    zone.addEventListener(name, (event) => {
      event.preventDefault();
      zone.classList.add("is-dragover");
    })
  );
  ["dragleave", "drop"].forEach((name) => zone.addEventListener(name, () => zone.classList.remove("is-dragover")));
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    classifyFile(event.dataTransfer.files[0]);
  });
}

async function loadSamples() {
  const samples = await fetch("/api/samples").then((r) => r.json()).catch(() => []);
  if (!samples.length) return;
  $("samples-block").hidden = false;
  for (const sample of samples) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.className = "thumb";
    button.type = "button";
    button.innerHTML = `<img src="/images/${escapeHtml(sample.isic_id)}.jpg" alt="Test lesion ${escapeHtml(sample.isic_id)}" loading="lazy">`;
    button.addEventListener("click", () => {
      showImage(`/images/${sample.isic_id}.jpg`);
      classify(fetch(`/api/classify/${sample.isic_id}`, { method: "POST" }), sample);
      $("check").scrollIntoView({ block: "start" });
    });
    item.append(button);
    $("samples").append(item);
  }
}

/* ---------- Test results ---------- */
let report = null;
let threshold = 0.5;
let caseFilter = "all";
let casesShown = 48;

function wilson(k, n) {
  if (!n) return null;
  const z = 1.96, p = k / n, denom = 1 + (z * z) / n;
  const centre = (p + (z * z) / (2 * n)) / denom;
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / denom;
  return [Math.max(0, centre - half), Math.min(1, centre + half)];
}
const answered = () => report.cases.filter((c) => c.probability != null);
const outcome = (c) => {
  const flagged = c.probability >= threshold;
  if (c.label === "malignant") return flagged ? "tp" : "fn";
  return flagged ? "fp" : "tn";
};
function counts() {
  const tally = { tp: 0, fp: 0, tn: 0, fn: 0 };
  for (const c of answered()) tally[outcome(c)]++;
  return tally;
}

function renderHeadline(c) {
  const refused = report.dataset.refused;
  $("headline").innerHTML =
    `At a ${pct(threshold)} cut-off it flagged <strong>${c.tp} of ${c.tp + c.fn}</strong> cancers and cleared ` +
    `<strong>${c.tn} of ${c.tn + c.fp}</strong> benign lesions.` +
    (refused ? ` It declined to answer for ${refused}.` : "");
}

function renderStats(c) {
  const total = c.tp + c.fp + c.tn + c.fn;
  const rows = [
    ["Accuracy", c.tp + c.tn, total, "all lesions called correctly"],
    ["Sensitivity", c.tp, c.tp + c.fn, "cancers caught"],
    ["Specificity", c.tn, c.tn + c.fp, "benign lesions cleared"],
    ["Precision", c.tp, c.tp + c.fp, "malignant calls that were right"],
  ];
  const cells = rows.map(([name, k, n, meaning]) => {
    const ci = wilson(k, n);
    const range = ci ? `95% range ${pct(ci[0])} to ${pct(ci[1])}` : "no cases";
    return `<div><dt>${name}</dt><dd>${n ? pct(k / n, 1) : "n/a"}</dd><small>${meaning}<br>${range}</small></div>`;
  });
  const latency = report.latency_ms;
  cells.push(
    `<div><dt>AUC</dt><dd>${report.auc == null ? "n/a" : report.auc.toFixed(3)}</dd><small>ranking quality, any cut-off<br>0.5 is chance, 1 is perfect</small></div>`,
    `<div><dt>Median response</dt><dd>${Math.round(latency.p50)} ms</dd><small>per image<br>95th percentile ${Math.round(latency.p95)} ms</small></div>`
  );
  $("stats").innerHTML = cells.join("");
}

function renderMatrix(c) {
  const cell = (key, label) =>
    `<td><button type="button" data-filter="${key}" aria-pressed="${caseFilter === key}"><b>${c[key]}</b><span>${label}</span></button></td>`;
  $("matrix").innerHTML = `
    <tr><td></td><th scope="col">Called malignant</th><th scope="col">Called benign</th></tr>
    <tr><th scope="row">Malignant</th>${cell("tp", "caught")}${cell("fn", "missed")}</tr>
    <tr><th scope="row">Benign</th>${cell("fp", "false alarms")}${cell("tn", "cleared")}</tr>`;
  $("matrix").querySelectorAll("button").forEach((button) =>
    button.addEventListener("click", () => setFilter(caseFilter === button.dataset.filter ? "all" : button.dataset.filter))
  );
}

/* Charts share one plot frame: 0..1 on x, caller-defined y. */
const W = 460, H = 320, M = { top: 14, right: 18, bottom: 44, left: 48 };
const PW = W - M.left - M.right, PH = H - M.top - M.bottom;
const sx = (v) => M.left + v * PW;

function frame(container, { xTitle, yTitle, yTicks, sy, yFormat = pct, label }) {
  container.replaceChildren();
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": label }, container);
  for (const t of yTicks) {
    svg("line", { x1: M.left, x2: W - M.right, y1: sy(t), y2: sy(t), class: "gridline" }, root);
    svg("text", { x: M.left - 8, y: sy(t) + 4, "text-anchor": "end" }, root).textContent = yFormat(t);
  }
  for (const t of [0, 0.25, 0.5, 0.75, 1]) {
    svg("text", { x: sx(t), y: H - M.bottom + 18, "text-anchor": "middle" }, root).textContent = pct(t);
  }
  svg("text", { x: M.left + PW / 2, y: H - 6, "text-anchor": "middle", class: "axis-title" }, root).textContent = xTitle;
  svg("text", { x: 12, y: M.top + PH / 2, "text-anchor": "middle", class: "axis-title", transform: `rotate(-90 12 ${M.top + PH / 2})` }, root).textContent = yTitle;
  return root;
}

function renderRoc(c) {
  const sy = (v) => M.top + (1 - v) * PH;
  const root = frame($("roc"), {
    xTitle: "Benign lesions wrongly flagged", yTitle: "Cancers caught", yTicks: [0, 0.25, 0.5, 0.75, 1], sy,
    label: "ROC curve: cancers caught against benign lesions wrongly flagged",
  });
  svg("line", { x1: sx(0), y1: sy(0), x2: sx(1), y2: sy(1), class: "reference" }, root);
  svg("text", { x: sx(0.62), y: sy(0.55) + 14 }, root).textContent = "Chance";
  svg("polyline", { points: report.roc.map((p) => `${sx(p.fpr)},${sy(p.tpr)}`).join(" "), class: "line" }, root);

  const fpr = c.fp / (c.fp + c.tn || 1), tpr = c.tp / (c.tp + c.fn || 1);
  svg("circle", { cx: sx(fpr), cy: sy(tpr), r: 6, class: "dot" }, root);
  const right = fpr > 0.6;
  svg("text", { x: sx(fpr) + (right ? -12 : 12), y: sy(tpr) + 16, class: "direct", "text-anchor": right ? "end" : "start" }, root)
    .textContent = `${pct(threshold)} cut-off`;

  const hit = svg("rect", { x: M.left, y: M.top, width: PW, height: PH, class: "hit" }, root);
  const marker = svg("circle", { r: 5, class: "dot", visibility: "hidden" }, root);
  hit.addEventListener("pointermove", (event) => {
    const box = hit.getBoundingClientRect();
    const x = (event.clientX - box.left) / box.width;
    const point = report.roc.reduce((best, p) => (Math.abs(p.fpr - x) < Math.abs(best.fpr - x) ? p : best));
    marker.setAttribute("cx", sx(point.fpr));
    marker.setAttribute("cy", sy(point.tpr));
    marker.setAttribute("visibility", "visible");
    const cut = point.threshold == null ? "Above every score" : `Cut-off ${pct(point.threshold)}`;
    showTip(event, `${cut}<br>${pct(point.tpr)} of cancers caught<br>${pct(point.fpr)} of benign flagged`);
  });
  hit.addEventListener("pointerleave", () => {
    marker.setAttribute("visibility", "hidden");
    hideTip();
  });
  $("auc").textContent = report.auc == null ? "" : `AUC ${report.auc.toFixed(3)}`;
}

function renderHistogram() {
  const BINS = 20;
  const bins = Array.from({ length: BINS }, () => ({ malignant: 0, benign: 0 }));
  for (const c of answered()) bins[Math.min(BINS - 1, Math.floor(c.probability * BINS))][c.label]++;
  const peak = Math.max(1, ...bins.flatMap((b) => [b.malignant, b.benign]));
  const step = Math.max(1, Math.ceil(peak / 3 / 5) * 5);
  const top = Math.ceil(peak / step) * step;
  const mid = M.top + PH / 2;
  const sy = (v) => mid - (v / top) * (PH / 2);
  const ticks = [];
  for (let t = -top; t <= top; t += step) ticks.push(t);
  const root = frame($("histogram"), {
    xTitle: "Probability of malignancy given by the model", yTitle: "Lesions", yTicks: ticks, sy,
    yFormat: (t) => Math.abs(t), label: "Histogram of model probabilities for malignant and benign lesions",
  });
  const width = PW / BINS - 2;
  bins.forEach((bin, i) => {
    const x = sx(i / BINS) + 1;
    const range = `${pct(i / BINS)} to ${pct((i + 1) / BINS)}`;
    for (const [label, sign] of [["malignant", 1], ["benign", -1]]) {
      if (!bin[label]) continue;
      const height = (bin[label] / top) * (PH / 2) - 1;
      const y = sign > 0 ? mid - 1 - height : mid + 1;
      const r = Math.min(4, height / 2);
      const path = sign > 0
        ? `M${x},${y + height} V${y + r} Q${x},${y} ${x + r},${y} H${x + width - r} Q${x + width},${y} ${x + width},${y + r} V${y + height} Z`
        : `M${x},${y} V${y + height - r} Q${x},${y + height} ${x + r},${y + height} H${x + width - r} Q${x + width},${y + height} ${x + width},${y + height - r} V${y} Z`;
      tip(svg("path", { d: path, class: `fill-${label}` }, root), `Probability ${range}<br>${bin[label]} ${label} lesions`);
    }
  });
  svg("line", { x1: sx(threshold), x2: sx(threshold), y1: M.top, y2: M.top + PH, class: "cut" }, root);
  const right = threshold > 0.7;
  svg("text", { x: sx(threshold) + (right ? -6 : 6), y: M.top + 10, class: "direct", "text-anchor": right ? "end" : "start" }, root)
    .textContent = "Cut-off";
}

function renderCalibration() {
  const sy = (v) => M.top + (1 - v) * PH;
  const root = frame($("calibration"), {
    xTitle: "Probability the model stated", yTitle: "Share that were malignant", yTicks: [0, 0.25, 0.5, 0.75, 1], sy,
    label: "Calibration: stated probability against observed share malignant",
  });
  svg("line", { x1: sx(0), y1: sy(0), x2: sx(1), y2: sy(1), class: "reference" }, root);
  svg("text", { x: sx(0.72), y: sy(0.72) + 22 }, root).textContent = "Perfectly calibrated";
  const filled = report.calibration.bins.filter((b) => b.n > 0);
  svg("polyline", { points: filled.map((b) => `${sx(b.mean_probability)},${sy(b.observed)}`).join(" "), class: "line" }, root);
  for (const b of filled) {
    const dot = svg("circle", { cx: sx(b.mean_probability), cy: sy(b.observed), r: 5, class: "dot" }, root);
    const target = svg("circle", { cx: sx(b.mean_probability), cy: sy(b.observed), r: 14, class: "hit" }, root);
    tip(target, `Stated ${pct(b.low)} to ${pct(b.high)} (average ${pct(b.mean_probability)})<br>${pct(b.observed)} were malignant<br>${b.n} lesions`);
    dot.setAttribute("aria-hidden", "true");
  }
  const { ece, brier } = report.calibration;
  $("ece").textContent = ece == null ? "" : `average gap ${pct(ece, 1)}, Brier ${brier.toFixed(3)}`;
}

function renderDiagnoses() {
  const groups = new Map();
  for (const c of answered()) {
    const g = groups.get(c.diagnosis) ?? { diagnosis: c.diagnosis, label: c.label, n: 0, correct: 0, sum: 0, typed: 0, typeCorrect: 0 };
    g.n++;
    g.sum += c.probability;
    if (["tp", "tn"].includes(outcome(c))) g.correct++;
    if (c.predicted_type) {
      g.typed++;
      if (c.predicted_type === c.true_type) g.typeCorrect++;
    }
    groups.set(c.diagnosis, g);
  }
  const rows = [...groups.values()].sort((a, b) => (a.label === b.label ? b.n - a.n : a.label === "malignant" ? -1 : 1));
  $("diagnoses").innerHTML =
    `<thead><tr><th>Confirmed diagnosis</th><th>Class</th><th class="num">Lesions</th><th>Called correctly at this cut-off</th><th class="num">95% range</th><th class="num">Average probability</th><th class="num">Exact diagnosis named</th></tr></thead><tbody>` +
    rows.map((g) => {
      const ci = wilson(g.correct, g.n);
      return `<tr><td>${escapeHtml(g.diagnosis)}</td><td><span class="key key-${escapeHtml(g.label)}"></span>${escapeHtml(g.label)}</td><td class="num">${g.n}</td>
        <td><span class="ratebar"><i><b class="key-${g.label}" style="width:${(g.correct / g.n) * 100}%"></b></i>${pct(g.correct / g.n)}</span></td>
        <td class="num">${pct(ci[0])} to ${pct(ci[1])}</td><td class="num">${pct(g.sum / g.n)}</td>
        <td class="num">${g.typed ? `${g.typeCorrect} of ${g.typed}` : "n/a"}</td></tr>`;
    }).join("") + "</tbody>";
}

const FILTERS = [
  ["all", "All"], ["fn", "Missed cancers"], ["fp", "False alarms"], ["tp", "Cancers caught"], ["tn", "Benign cleared"],
];
function setFilter(name) {
  caseFilter = name;
  casesShown = 48;
  renderMatrix(counts());
  renderCases();
}
function renderCases() {
  $("filters").replaceChildren(
    ...FILTERS.map(([key, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.setAttribute("aria-pressed", caseFilter === key);
      button.addEventListener("click", () => setFilter(key));
      return button;
    })
  );
  const wrongFirst = (c) => Math.abs(c.probability - (c.label === "malignant" ? 1 : 0));
  const matches = answered()
    .filter((c) => caseFilter === "all" || outcome(c) === caseFilter)
    .sort((a, b) => wrongFirst(b) - wrongFirst(a));
  const title = FILTERS.find(([key]) => key === caseFilter)[1];
  $("cases-title").textContent = `${caseFilter === "all" ? "All lesions" : title} (${matches.length}), most wrong first`;
  $("case-grid").replaceChildren(
    ...matches.slice(0, casesShown).map((c) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "thumb";
      button.innerHTML =
        `<img src="/images/${escapeHtml(c.isic_id)}.jpg" alt="${escapeHtml(c.diagnosis)}, ${escapeHtml(c.isic_id)}" loading="lazy">` +
        `<span class="cap"><b>${pct(c.probability)}</b> malignant<br><span class="swatch key-${c.label}"></span>${escapeHtml(c.diagnosis)}</span>`;
      button.addEventListener("click", () => {
        showImage(`/images/${c.isic_id}.jpg`);
        $("error").hidden = true;
        showResult(
          { malignant_probability: c.probability, latency_ms: c.latency_ms, model: report.model, lesion_type_probabilities: {} },
          { label: c.label, diagnosis: c.diagnosis }
        );
        $("result-meta").textContent += ` Stored result from the test run${c.predicted_type ? `; closest diagnosis named: ${typeName(c.predicted_type).toLowerCase()}` : ""}.`;
        $("check").scrollIntoView({ block: "start" });
      });
      item.append(button);
      return item;
    })
  );
  $("more-cases").hidden = matches.length <= casesShown;
}

function renderThresholdDependent() {
  const c = counts();
  $("threshold-out").textContent = pct(threshold);
  renderHeadline(c);
  renderStats(c);
  renderMatrix(c);
  renderRoc(c);
  renderHistogram();
  renderDiagnoses();
  renderCases();
}

async function loadResults() {
  const response = await fetch("/api/evaluation").catch(() => null);
  if (!response || !response.ok) {
    $("results-empty").hidden = false;
    return;
  }
  report = await response.json();
  threshold = report.threshold;
  $("threshold").value = Math.round(threshold * 100);
  $("n-cases").textContent = report.dataset.answered;
  $("results-body").hidden = false;
  renderCalibration();
  renderThresholdDependent();

  $("threshold").addEventListener("input", (event) => {
    threshold = Number(event.target.value) / 100;
    renderThresholdDependent();
  });
  $("threshold-reset").addEventListener("click", () => {
    threshold = report.threshold;
    $("threshold").value = Math.round(threshold * 100);
    renderThresholdDependent();
  });
  $("more-cases").addEventListener("click", () => {
    casesShown += 48;
    renderCases();
  });
}

setupCheck();
fetch("/api/config").then((r) => r.json()).then((config) => (lesionTypes = config.lesion_types)).catch(() => {});
loadSamples();
loadResults();
