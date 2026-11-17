/* ---- the page: shared by both languages; every visible word comes from T (set by the language's markup) ---- */
const $ = id => document.getElementById(id);
const N = t => `<span class="num">${t}</span>`;
const f1 = x => (Math.abs(x) < 0.05 ? 0 : x).toFixed(1).replace("-", "−");
const f0 = x => (Math.round(x) || 0).toLocaleString("en-US").replace("-", "−");     // never "−0"
const NS = "http://www.w3.org/2000/svg";
const el = (name, attrs = {}, text) => { const e = document.createElementNS(NS, name); for (const k in attrs) e.setAttribute(k, attrs[k]); if (text !== undefined) e.textContent = text; return e; };
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const RTL = document.documentElement.dir === "rtl";
const LEFT_OF = RTL ? "start" : "end";      // the anchor that puts a label to the left of its point, in either direction
const PRESETS = { il: { pcar: 1.35, pbus: 20, npax: 6, doors: 2 }, ilpeak: { pcar: 1.2, pbus: 20, npax: 10, doors: 2 }, us: { pcar: 1.7, pbus: 10.7, npax: 6, doors: 1 } };
const S = { rate: 0.3, pbus: 20, pcar: 1.35, npax: 6, doors: 2, link: "pen", dLane: 6, dBay: 6 };
const A = Object.assign({}, DEFAULT_ADV);
const ADV_KEYS = ["m2", "m3", "longPen", "latPen", "devLane", "devBay", "gapLane", "gapBay", "entryExtra"];
const ADV_STEP = { m2: "0.05", m3: "0.05", longPen: "0.05", latPen: "0.01", devLane: "0.1", devBay: "0.1", gapLane: "0.05", gapBay: "0.05", entryExtra: "0.5" };
const ADV_TAG = { m2: "guess", m3: "guess", longPen: "guess", latPen: "guess", devLane: "sim", devBay: "guess", gapLane: "sim", gapBay: "guess", entryExtra: "guess" };
function buildAdv() {
  $("advgrid").innerHTML = ADV_KEYS.map(k => { const [label, why] = T.adv[k]; const tag = ADV_TAG[k];
    return `<div class="f"><label for="adv-${k}">${label}<span class="tag ${tag}">${T.tags[tag]}</span></label><input type="number" id="adv-${k}" step="${ADV_STEP[k]}" value="${A[k]}"><span class="why">${why}</span></div>`; }).join("");
  ADV_KEYS.forEach(k => $("adv-" + k).addEventListener("input", () => { const v = parseFloat($("adv-" + k).value); if (!isNaN(v)) { A[k] = v; renderAll(); } }));
}
function current() { const d = dwells(S, A); return { d, r: evaluate(S.pcar, S.pbus, S.rate, d.lane, d.bay, A.entryExtra) }; }

function readControls() {
  S.rate = +$("rate").value; S.pbus = +$("pbus").value; S.pcar = +$("pcar").value; S.npax = +$("npax").value;
  S.dLane = +$("dlane").value; S.dBay = +$("dbay").value;
  if (S.link !== "free") { const d = dwells(S, A); $("dbay").value = Math.round(d.bay); }
  $("dbay").disabled = S.link !== "free";
  document.querySelectorAll("#dlink button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.l === S.link)));
  document.querySelectorAll("#doors button").forEach(b => b.setAttribute("aria-pressed", String(+b.dataset.d === S.doors)));
  document.querySelectorAll(".presets button").forEach(b => { const p = PRESETS[b.dataset.p]; b.setAttribute("aria-pressed", String(Math.abs(p.pcar - S.pcar) < 0.01 && Math.abs(p.pbus - S.pbus) < 0.01 && p.npax === S.npax && p.doors === S.doors)); });
}
function renderControls() {
  $("rate-v").innerHTML = N(S.rate.toFixed(2)); $("rate-h").textContent = T.rateHint(f0(S.rate * 3600));
  $("pbus-v").innerHTML = N(S.pbus); $("pcar-v").innerHTML = N(S.pcar.toFixed(2)); $("npax-v").innerHTML = N(S.npax);
  const d = dwells(S, A);
  $("dw-v").innerHTML = T.dwBoth(N(f1(d.lane)), N(f1(d.bay)));
  $("dlane-v").innerHTML = `${N(S.dLane)} ${T.s}`; $("dbay-v").innerHTML = `${N(f1(d.bay))} ${T.s}`;
  $("dw-h").innerHTML = S.link === "pen" ? T.dwPen(N(S.dLane), N(f1(d.extra)), N(S.npax), N(S.doors)) : S.link === "same" ? T.dwSame : T.dwFree;
  $("pcar-band").style.left = "20%"; $("pcar-band").style.right = "50%";
}
function renderResult() {
  const { d, r } = current(), box = $("verdict-box"); box.className = r.verdict;
  $("verdict-title").textContent = T.verdict[r.verdict];
  let text = r.verdict === "tie" ? T.tieText(f1(r.mean / 60)) : T.winText(r.verdict, f1(Math.abs(r.mean) / 60), f1(Math.abs(r.perPerson)));
  text += T.stopText(f1(d.lane), f1(d.bay));
  if (r.laneAlways) text += T.laneAlways;
  else if (r.bayAlways) text += T.bayAlways;
  else if (r.breakEvenBus !== null) text += T.breakEven(f1(r.breakEvenBus), r.breakEvenCar < 10 ? r.breakEvenCar.toFixed(2) : f0(r.breakEvenCar));
  $("verdict-text").textContent = text;
  $("facts").innerHTML = [[T.factDiff, `${N(f1(r.mean / 60))} ${T.pmin}`], [T.factCi, T.range(N(f1(r.lo / 60)), N(f1(r.hi / 60)))]]
    .map(([k, v]) => `<div class="fact"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
  const q = queueAt(S.rate, d.lane), carsLose = r.b < 0, carMin = Math.abs(r.carPart) / 60;
  $("pens").innerHTML = `
    <div class="pen bayp"><h3>${T.penBay}</h3><div class="who">${T.penBayWho}</div>
      <div class="big">${N(f1(r.busPart / 60))} ${T.pmin}</div>
      <dl><dt>${T.penBayLonger}</dt><dd>${N(f1(d.bay - d.lane))} ${T.s}</dd>
          <dt>${T.penBayEntry}</dt><dd>${N(f1(A.entryExtra))} ${T.s}</dd>
          <dt>${T.penBayMerge}</dt><dd>${N(f1(r.a - (d.bay - d.lane) - A.entryExtra))} ${T.s}</dd>
          <dt>${T.penBayTotal}</dt><dd>${N(f1(r.a))} ${T.s}</dd></dl></div>
    <div class="pen lanep"><h3>${carsLose ? T.penLane : T.penLaneSlower}</h3><div class="who">${carsLose ? T.penLaneWho : T.penLaneSlowerWho}</div>
      <div class="big">${N(f1(carMin))} ${T.pmin}</div>
      <dl><dt>${T.penLaneDwell}</dt><dd>${N(f1(d.lane))} ${T.s}</dd>
          <dt>${T.penLaneQueue}</dt><dd>${N(f1(q))} ${T.carsWord}</dd>
          <dt>${T.penLaneTotal}</dt><dd>${N(f1(Math.abs(r.b) / 60))} ${carsLose ? T.vminMoreLane : T.vminMoreBay}</dd></dl></div>`;
  const onGrid = AXIS_R.some(x => Math.abs(x - S.rate) < 1e-9) && AXIS_D.some(x => Math.abs(x - d.lane) < 1e-9) && AXIS_D.some(x => Math.abs(x - d.bay) < 1e-9);
  $("interp-note").textContent = onGrid ? T.onGrid : T.offGrid;
}
function queueAt(rate, d) {
  const [r0, r1, wr] = bracket(AXIS_R, rate), [d0, d1, wd] = bracket(AXIS_D, d), Q = DATA.lane_queue_cars;
  const at = (ri, di) => Q[key(AXIS_R[ri])][String(AXIS_D[di])];
  return (1 - wr) * ((1 - wd) * at(r0, d0) + wd * at(r0, d1)) + wr * ((1 - wd) * at(r1, d0) + wd * at(r1, d1));
}
function niceStep(raw) { const p = Math.pow(10, Math.floor(Math.log10(raw))), m = raw / p; return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p; }
function renderPbusChart() {
  const svg = $("chart-pbus"); svg.innerHTML = "";
  const x0 = 70, x1 = 730, yt = 20, yb = 300, XMAX = 80, d = dwells(S, A);
  const pts = []; for (let pb = 0; pb <= XMAX; pb += 2) pts.push([pb, evaluate(S.pcar, pb, S.rate, d.lane, d.bay, A.entryExtra)]);
  const vals = pts.flatMap(([, r]) => [r.lo / 60, r.hi / 60, r.mean / 60]); let ymin = Math.min(...vals, -1), ymax = Math.max(...vals, 1);
  const pad = (ymax - ymin) * 0.08; ymin -= pad; ymax += pad;
  const sx = v => x0 + (x1 - x0) * v / XMAX, sy = v => yb - (yb - yt) * (v - ymin) / (ymax - ymin);
  svg.appendChild(el("rect", { x: x0, y: yt, width: x1 - x0, height: sy(0) - yt, fill: css("--lane-soft") }));
  svg.appendChild(el("rect", { x: x0, y: sy(0), width: x1 - x0, height: yb - sy(0), fill: css("--bay-soft") }));
  const step = niceStep((ymax - ymin) / 5);
  for (let v = Math.ceil(ymin / step) * step; v <= ymax; v += step) {
    svg.appendChild(el("line", { x1: x0, x2: x1, y1: sy(v), y2: sy(v), stroke: css("--line"), "stroke-width": 1 }));
    svg.appendChild(el("text", { x: x0 - 8, y: sy(v) + 4, "text-anchor": LEFT_OF, "font-size": 12, class: "muted" }, f0(v)));
  }
  svg.appendChild(el("line", { x1: x0, x2: x1, y1: sy(0), y2: sy(0), stroke: css("--ink"), "stroke-width": 1.5 }));
  const band = pts.map(([pb, r]) => `${sx(pb)},${sy(r.hi / 60)}`).concat(pts.slice().reverse().map(([pb, r]) => `${sx(pb)},${sy(r.lo / 60)}`)).join(" ");
  svg.appendChild(el("polygon", { points: band, fill: css("--accent"), opacity: 0.22 }));
  svg.appendChild(el("polyline", { points: pts.map(([pb, r]) => `${sx(pb)},${sy(r.mean / 60)}`).join(" "), fill: "none", stroke: css("--accent"), "stroke-width": 2.8 }));
  [[10.7, "10.7"], [20, "20"]].forEach(([v, t]) => {
    svg.appendChild(el("line", { x1: sx(v), x2: sx(v), y1: yt, y2: yb, stroke: css("--muted"), "stroke-width": 1, "stroke-dasharray": "4 4" }));
    svg.appendChild(el("text", { x: sx(v), y: yt + 12, "text-anchor": "middle", "font-size": 11, class: "muted" }, t)); });
  [0, 20, 40, 60, 80].forEach(v => svg.appendChild(el("text", { x: sx(v), y: yb + 20, "text-anchor": "middle", "font-size": 12, class: "muted" }, String(v))));
  svg.appendChild(el("text", { x: (x0 + x1) / 2, y: yb + 42, "text-anchor": "middle", "font-size": 13, class: "muted" }, T.axisBus));
  svg.appendChild(el("text", { x: 16, y: (yt + yb) / 2, "text-anchor": "middle", "font-size": 13, class: "muted", transform: `rotate(-90 16 ${(yt + yb) / 2})` }, T.axisPmin));
  svg.appendChild(el("text", { x: x1 - 6, y: yt + 30, "text-anchor": LEFT_OF, "font-size": 13, style: "fill:" + css("--lane") }, T.verdict.lane));
  svg.appendChild(el("text", { x: x1 - 6, y: yb - 10, "text-anchor": LEFT_OF, "font-size": 13, style: "fill:" + css("--bay") }, T.verdict.bay));
  const cur = current().r; svg.appendChild(el("circle", { cx: sx(Math.min(S.pbus, XMAX)), cy: sy(cur.mean / 60), r: 7, fill: css("--surface"), stroke: css("--ink"), "stroke-width": 3 }));
}
function renderMap() {
  const map = $("map"), cols = [], rows = AXIS_D.slice().reverse();
  for (let i = 0; i < 9; i++) cols.push(+(0.1 + 0.05 * i).toFixed(2));
  let html = '<span></span>' + cols.map(c => `<span class="h">${c.toFixed(2)}</span>`).join("");
  const cur = dwells(S, A), nearR = cols.reduce((a, c) => Math.abs(c - S.rate) < Math.abs(a - S.rate) ? c : a), nearD = rows.reduce((a, d) => Math.abs(d - cur.base) < Math.abs(a - cur.base) ? d : a);
  const extraLane = cur.lane - cur.base, extraBay = cur.bay - cur.base, cl = x => Math.min(45, Math.max(0, x));
  rows.forEach(dd => { html += `<span class="h">${dd}</span>`; cols.forEach(c => { const r = evaluate(S.pcar, S.pbus, c, cl(dd + extraLane), cl(dd + extraBay), A.entryExtra);
    html += `<span class="c ${r.verdict}${c === nearR && dd === nearD ? " now" : ""}" title="${T.verdict[r.verdict]}">${f1(r.mean / 60)}</span>`; }); });
  map.innerHTML = html;
}
/* inside a documentation page (an iframe), tell the page how tall this one is, so it needs no scroll bar of its own */
function postHeight() { if (window.parent !== window) window.parent.postMessage({ type: "stop-explorer-height", h: document.documentElement.scrollHeight }, "*"); }
function renderAll() { readControls(); renderControls(); renderResult(); renderPbusChart(); renderMap(); postHeight(); }
["rate", "pbus", "pcar", "npax", "dlane", "dbay"].forEach(id => $(id).addEventListener("input", renderAll));
document.querySelectorAll("#dlink button").forEach(b => b.addEventListener("click", () => { S.link = b.dataset.l; renderAll(); }));
document.querySelectorAll("#doors button").forEach(b => b.addEventListener("click", () => { S.doors = +b.dataset.d; renderAll(); }));
document.querySelectorAll(".presets button").forEach(b => b.addEventListener("click", () => { const p = PRESETS[b.dataset.p]; $("pcar").value = p.pcar; $("pbus").value = p.pbus; $("npax").value = p.npax; S.doors = p.doors; renderAll(); }));
$("reset-adv").addEventListener("click", () => { Object.assign(A, DEFAULT_ADV); ADV_KEYS.forEach(k => { $("adv-" + k).value = A[k]; }); renderAll(); });
$("prov").textContent = T.prov(DATA.provenance.map(p => T.provItem(p.experiment, p.runs_stored.toLocaleString("en-US"), p.commit, p.brain_version, p.date.slice(0, 10))).join("; "));
if (new URLSearchParams(location.search).has("embed")) document.documentElement.classList.add("embed");
buildAdv(); renderAll();
if (window.ResizeObserver) new ResizeObserver(postHeight).observe(document.body);
window.addEventListener("load", postHeight);
if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderAll);
new MutationObserver(renderAll).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
