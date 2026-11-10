/* ---- the model: pure functions, also used by the tests ---- */
const AXIS_R = DATA.rates, AXIS_D = DATA.dwells, Z = 1.96, WINDOW_S = 150;
function bracket(axis, v) {
  const x = Math.min(Math.max(v, axis[0]), axis[axis.length - 1]);
  let i = 0; while (i < axis.length - 2 && x > axis[i + 1]) i++;
  return [i, i + 1, (x - axis[i]) / (axis[i + 1] - axis[i])];
}
const key = r => String(+r.toFixed(1));
function stats(rate, dl, db) {            // trilinear interpolation of [n, a, b, va, vb, cab]
  const [r0, r1, wr] = bracket(AXIS_R, rate), [l0, l1, wl] = bracket(AXIS_D, dl), [b0, b1, wb] = bracket(AXIS_D, db);
  const out = [0, 0, 0, 0, 0, 0];
  for (const [ri, rw] of [[r0, 1 - wr], [r1, wr]]) for (const [li, lw] of [[l0, 1 - wl], [l1, wl]]) for (const [bi, bw] of [[b0, 1 - wb], [b1, wb]]) {
    const w = rw * lw * bw; if (!w) continue;
    const v = DATA.pairs[key(AXIS_R[ri])][String(AXIS_D[li])][String(AXIS_D[bi])];
    for (let k = 0; k < 6; k++) out[k] += w * v[k];
  }
  return out;
}
function evaluate(pc, pb, rate, dl, db, entryExtra = 0) {
  const [n, a0, b, va, vb, c] = stats(rate, dl, db), a = a0 + entryExtra;
  const mean = pb * a + pc * b, se = Z * Math.sqrt(Math.max(pb * pb * va + pc * pc * vb + 2 * pb * pc * c, 0) / n);
  const verdict = mean + se < 0 ? "bay" : mean - se > 0 ? "lane" : "tie";
  const persons = pb + pc * rate * WINDOW_S;
  return { n, a, b, mean, lo: mean - se, hi: mean + se, verdict, busPart: pb * a, carPart: pc * b, persons,
           perPerson: mean / persons, breakEvenBus: a * b < 0 ? -pc * b / a : null, breakEvenCar: a * b < 0 ? -pb * a / b : null,
           laneAlways: a > 0 && b > 0, bayAlways: a < 0 && b < 0 };
}
/* stop times of the two designs from the page's assumptions */
const DEFAULT_ADV = { m2: 0.7, m3: 0.6, longPen: 0.4, latPen: 0.05,
  devLane: DATA.geometry.dev_lane_m, devBay: +(DATA.geometry.dev_bay_m + 1.0).toFixed(2), gapLane: DATA.geometry.gap_lane_m, gapBay: +(DATA.geometry.gap_bay_m + 0.4).toFixed(2), entryExtra: 1.0 };
const doorMult = (S, A) => S.doors === 1 ? 1 : S.doors === 2 ? A.m2 : A.m3;
function baseDwell(S) { return S.dLane; }
function geometryPenalty(S, A, dev, gap) { const m = doorMult(S, A); return A.longPen * dev * m + A.latPen * S.npax * m * (gap / 0.1); }
function dwells(S, A) {                            // the lane time is taken as typed; the bay time follows the chosen link
  const cl = x => Math.min(AXIS_D[AXIS_D.length - 1], Math.max(0, x));
  const extra = geometryPenalty(S, A, A.devBay, A.gapBay) - geometryPenalty(S, A, A.devLane, A.gapLane);
  const bay = S.link === "free" ? S.dBay : S.link === "same" ? S.dLane : S.dLane + extra;
  return { base: S.dLane, lane: cl(S.dLane), bay: cl(bay), extra };
}
window.Explorer = { evaluate, stats, dwells, baseDwell, geometryPenalty, DEFAULT_ADV, DATA };
