import React, { useState, useRef, useEffect, useMemo, useCallback } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ReferenceLine, Area, AreaChart,
} from "recharts";
import { Atom, Play, Pause, RotateCcw, Plus, Radio, Waves, Orbit, Gauge } from "lucide-react";

/* =============================================================================
   PHYSICS CORE — mirrors the Python ARC-SIM package exactly, running live
   in-browser so every slider recomputes real numbers, not canned frames.
============================================================================= */
const MEV_TO_J = 1.602176634e-13;
const KEV_TO_J = 1.602176634e-16;
const MU0 = 4e-7 * Math.PI;
const E_DT_FUSION_MEV = 17.59;
const E_ALPHA_MEV = 3.52;
const TRIPLE_PRODUCT_BREAKEVEN = 3.0e21;
const TRIPLE_PRODUCT_IGNITION = 5.0e21;

// Bosch-Hale D-T reactivity <sigma*v> [m^3/s], accurate ~0.25% from 0.2-100 keV
function dtReactivity(T) {
  if (T <= 0) return 0;
  const C1 = 1.17302e-9, C2 = 1.51361e-2, C3 = 7.51886e-2, C4 = 4.60643e-3,
    C5 = 1.35e-2, C6 = -1.0675e-4, C7 = 1.366e-5, B_G = 34.3827, mr_c2 = 1124656.0;
  const theta = T / (1 - (T * (C2 + T * (C4 + T * C6))) / (1 + T * (C3 + T * (C5 + T * C7))));
  const xi = Math.cbrt((B_G * B_G) / (4 * theta));
  const sigma_v = C1 * theta * Math.sqrt(xi / (mr_c2 * T ** 3)) * Math.exp(-3 * xi);
  return sigma_v * 1e-6; // cm^3/s -> m^3/s
}
const fusionPowerDensity = (n, T) => (n * n / 4) * dtReactivity(T) * E_DT_FUSION_MEV * MEV_TO_J;
const alphaPowerDensity = (n, T) => (n * n / 4) * dtReactivity(T) * E_ALPHA_MEV * MEV_TO_J;
const bremsstrahlungLoss = (n, T, Zeff = 1) => 5.35e-37 * Zeff * n * n * Math.sqrt(Math.max(T, 1e-9));
const tripleProduct = (n, T, tau) => n * T * tau;

function qFactor(n, T, tau) {
  const W = 3 * n * T * KEV_TO_J;
  const pTransport = W / tau;
  const pBrem = bremsstrahlungLoss(n, T);
  const pAlpha = alphaPowerDensity(n, T);
  const pFus = fusionPowerDensity(n, T);
  const pHeatNeeded = pTransport + pBrem - pAlpha;
  if (pHeatNeeded <= 0) return Infinity;
  return pFus / pHeatNeeded;
}

// Scalar RK4 step for the 0D energy balance ODE: dW/dt = alpha + ext - transport - brem
function dWdt(t, W, n, tau, Pext) {
  const T = Math.max(W / (3 * n * KEV_TO_J), 1e-3);
  return alphaPowerDensity(n, T) + Pext(t) - W / tau - bremsstrahlungLoss(n, T);
}
function rk4Step(t, W, h, n, tau, Pext) {
  const k1 = dWdt(t, W, n, tau, Pext);
  const k2 = dWdt(t + h / 2, W + (h / 2) * k1, n, tau, Pext);
  const k3 = dWdt(t + h / 2, W + (h / 2) * k2, n, tau, Pext);
  const k4 = dWdt(t + h, W + h * k3, n, tau, Pext);
  return W + (h / 6) * (k1 + 2 * k2 + 2 * k3 + k4);
}

// Beta limit: how dense a plasma a magnet of field B can hold at temperature T
function maxDensityFromBeta(B, T, beta = 0.05) {
  const pMag = (B * B) / (2 * MU0);
  return (beta * pMag) / (2 * T * KEV_TO_J);
}

// Tokamak field geometry (Phase 4)
function currentInside(r, a, Ip) {
  const x = Math.min(Math.max(r / a, 0), 1);
  return Ip * (2 * x * x - x ** 4);
}
function safetyFactor(r, a, R0, B0, Ip) {
  const Bpol = (MU0 * currentInside(r, a, Ip)) / (2 * Math.PI * Math.max(r, 1e-9));
  return (r * B0) / (R0 * Math.max(Bpol, 1e-12));
}
function traceFieldLine(R0, a, B0, Ip, rStart, lengthM = 260, steps = 900) {
  const ds = lengthM / steps;
  let x = R0 + rStart, y = 0, z = 0;
  const pts = [];
  const Bfield = (x, y, z) => {
    const R = Math.hypot(x, y);
    const phiHat = [-y / R, x / R, 0];
    const Btor = (B0 * R0) / R;
    const rMin = Math.hypot(R - R0, z);
    if (rMin < 1e-9) return [Btor * phiHat[0], Btor * phiHat[1], Btor * phiHat[2]];
    const Bpol = (MU0 * currentInside(rMin, a, Ip)) / (2 * Math.PI * rMin);
    const er = [((R - R0) * x) / R / rMin, ((R - R0) * y) / R / rMin, z / rMin];
    const thetaHat = [
      phiHat[1] * er[2] - phiHat[2] * er[1],
      phiHat[2] * er[0] - phiHat[0] * er[2],
      phiHat[0] * er[1] - phiHat[1] * er[0],
    ];
    return [
      Btor * phiHat[0] + Bpol * thetaHat[0],
      Btor * phiHat[1] + Bpol * thetaHat[1],
      Btor * phiHat[2] + Bpol * thetaHat[2],
    ];
  };
  for (let i = 0; i < steps; i++) {
    const B = Bfield(x, y, z);
    const mag = Math.hypot(B[0], B[1], B[2]) || 1;
    x += (ds * B[0]) / mag; y += (ds * B[1]) / mag; z += (ds * B[2]) / mag;
    pts.push([x, y, z]);
  }
  return pts;
}

// Radial 1D diffusion (Phase 3) — explicit finite difference to steady state
function solveRadialProfile(a, n, chi, Tedge, heatingMWperM, depositWidth, nr = 40) {
  const r = Array.from({ length: nr }, (_, i) => (i * a) / (nr - 1));
  const dr = r[1] - r[0];
  const w = depositWidth * a;
  const shape = r.map((ri) => Math.exp(-((ri / w) ** 2)));
  let integral = 0;
  for (let i = 1; i < nr; i++) integral += Math.PI * (r[i] + r[i - 1]) * dr * ((shape[i] + shape[i - 1]) / 2);
  const Sext = shape.map((s) => (s * heatingMWperM * 1e6) / Math.max(integral, 1e-30));

  let T = new Array(nr).fill(1.0);
  T[nr - 1] = Tedge;
  const tauEst = (a * a) / (4 * chi);
  const tEnd = 6 * tauEst;
  const dt = 0.2 * (dr * dr) / chi;
  const steps = Math.min(Math.ceil(tEnd / dt), 40000);
  const snapEvery = Math.max(1, Math.floor(steps / 5));
  const snapshots = [[0, T.slice()]];

  for (let s = 1; s <= steps; s++) {
    const Tn = T.slice();
    for (let i = 1; i < nr - 1; i++) {
      const rph = 0.5 * (r[i] + r[i + 1]), rmh = 0.5 * (r[i] + r[i - 1]);
      const fluxP = (rph * chi * (T[i + 1] - T[i])) / dr;
      const fluxM = (rmh * chi * (T[i] - T[i - 1])) / dr;
      const cond = (fluxP - fluxM) / (r[i] * dr);
      const heat = alphaPowerDensity(n, T[i]) + Sext[i] - bremsstrahlungLoss(n, T[i]);
      Tn[i] = Math.max(T[i] + dt * (cond + heat / (3 * n * KEV_TO_J)), 1e-3);
    }
    const cond0 = (4 * chi * (T[1] - T[0])) / (dr * dr);
    const heat0 = alphaPowerDensity(n, T[0]) + Sext[0] - bremsstrahlungLoss(n, T[0]);
    Tn[0] = Math.max(T[0] + dt * (cond0 + heat0 / (3 * n * KEV_TO_J)), 1e-3);
    Tn[nr - 1] = Tedge;
    T = Tn;
    if (s % snapEvery === 0 || s === steps) snapshots.push([s * dt, T.slice()]);
  }
  const ring = r.map((ri) => 2 * Math.PI * ri);
  let Pfus = 0;
  for (let i = 1; i < nr; i++) {
    const f0 = fusionPowerDensity(n, T[i - 1]) * ring[i - 1];
    const f1 = fusionPowerDensity(n, T[i]) * ring[i];
    Pfus += ((f0 + f1) / 2) * dr;
  }
  return { r, snapshots, T, tauEst, Pfus_MW_per_m: Pfus / 1e6 };
}

/* =============================================================================
   DESIGN TOKENS
============================================================================= */
const C = {
  bg: "#0a0c10", panel: "#12151c", panelBorder: "#232a35",
  ink: "#e8ecf1", sub: "#7c8898",
  fusion: "#ff8a3d", confine: "#3ddbff", danger: "#ff4d6d", ok: "#7cf29c",
  grid: "#1c2029",
};
const mono = { fontFamily: "'JetBrains Mono','IBM Plex Mono',monospace" };

function Slider({ label, value, onChange, min, max, step, unit, log }) {
  const disp = log ? Math.log10(value) : value;
  const dmin = log ? Math.log10(min) : min;
  const dmax = log ? Math.log10(max) : max;
  return (
    <div className="mb-4">
      <div className="flex justify-between items-baseline mb-1">
        <span className="text-xs tracking-wide" style={{ color: C.sub }}>{label}</span>
        <span className="text-sm" style={{ ...mono, color: C.ink }}>
          {value >= 1000 || value < 0.001 ? value.toExponential(2) : value.toFixed(value < 1 ? 3 : 2)}{unit}
        </span>
      </div>
      <input
        type="range" min={dmin} max={dmax} step={step || (dmax - dmin) / 200} value={disp}
        onChange={(e) => onChange(log ? 10 ** parseFloat(e.target.value) : parseFloat(e.target.value))}
        className="w-full accent-orange-500"
        style={{ accentColor: C.fusion }}
      />
    </div>
  );
}

function Panel({ title, children, className = "" }) {
  return (
    <div className={`rounded-lg p-4 ${className}`} style={{ background: C.panel, border: `1px solid ${C.panelBorder}` }}>
      {title && <div className="text-xs uppercase tracking-widest mb-3" style={{ color: C.sub, ...mono }}>{title}</div>}
      {children}
    </div>
  );
}

/* =============================================================================
   VIEW 1 — Triple Product Explorer (Phase 1, instant)
============================================================================= */
function TripleProductView() {
  const [n, setN] = useState(1.0e20);
  const [T, setT] = useState(15.0);
  const [tau, setTau] = useState(3.0);

  const tp = tripleProduct(n, T, tau);
  const Q = qFactor(n, T, tau);
  const pFus = fusionPowerDensity(n, T);
  const pBrem = bremsstrahlungLoss(n, T);
  const pct = Math.min((tp / TRIPLE_PRODUCT_BREAKEVEN) * 100, 999);
  const status = Q === Infinity ? "IGNITED" : Q >= 1 ? "BREAKEVEN" : "SUB-IGNITION";
  const statusColor = Q === Infinity ? C.ok : Q >= 1 ? C.fusion : C.danger;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Panel title="Plasma Parameters">
        <Slider label="Density n" value={n} onChange={setN} min={1e19} max={1e21} unit=" /m³" log />
        <Slider label="Temperature T" value={T} onChange={setT} min={1} max={100} step={0.5} unit=" keV" />
        <Slider label="Confinement time τ" value={tau} onChange={setTau} min={0.0005} max={10} unit=" s" log />
        <div className="text-xs mt-3" style={{ color: C.sub }}>
          T = {T} keV ≈ {(T * 11.6).toFixed(0)} million K
        </div>
      </Panel>

      <Panel title="Triple Product">
        <div className="text-3xl font-bold mb-1" style={{ ...mono, color: statusColor }}>
          {tp.toExponential(2)}
        </div>
        <div className="text-xs mb-4" style={{ color: C.sub }}>keV · s / m³ — breakeven at 3.0e21</div>
        <div className="h-3 rounded-full overflow-hidden mb-2" style={{ background: C.grid }}>
          <div className="h-full rounded-full transition-all" style={{
            width: `${Math.min(pct, 100)}%`,
            background: `linear-gradient(90deg, ${C.confine}, ${C.fusion})`,
          }} />
        </div>
        <div className="text-xs" style={{ color: C.sub }}>{pct.toFixed(1)}% of breakeven threshold</div>
        <div className="mt-4 pt-4" style={{ borderTop: `1px solid ${C.panelBorder}` }}>
          <div className="text-xs uppercase tracking-wide mb-1" style={{ color: C.sub }}>Status</div>
          <div className="text-2xl font-bold" style={{ ...mono, color: statusColor }}>{status}</div>
          <div className="text-sm mt-1" style={{ ...mono, color: C.ink }}>
            Q = {Q === Infinity ? "∞" : Q.toFixed(3)}
          </div>
        </div>
      </Panel>

      <Panel title="Power Densities">
        <div className="mb-3">
          <div className="text-xs" style={{ color: C.sub }}>Fusion power</div>
          <div className="text-xl" style={{ ...mono, color: C.fusion }}>{pFus.toExponential(2)} W/m³</div>
        </div>
        <div className="mb-3">
          <div className="text-xs" style={{ color: C.sub }}>Bremsstrahlung loss</div>
          <div className="text-xl" style={{ ...mono, color: C.danger }}>{pBrem.toExponential(2)} W/m³</div>
        </div>
        <div className="text-xs mt-4 leading-relaxed" style={{ color: C.sub }}>
          Every slider move recomputes the real Bosch-Hale D-T reactivity curve — this is the same
          equation used in actual fusion research, not a lookup table.
        </div>
      </Panel>
    </div>
  );
}

/* =============================================================================
   VIEW 2 — Energy Balance (Phase 2, live time evolution via RK4)
============================================================================= */
function EnergyBalanceView() {
  const [n, setN] = useState(1.0e20);
  const [tau, setTau] = useState(3.0);
  const [volume, setVolume] = useState(830);
  const [heatingMW, setHeatingMW] = useState(50);
  const [T0, setT0] = useState(2.0);
  const [running, setRunning] = useState(false);
  const [data, setData] = useState([]);
  const stateRef = useRef({ t: 0, W: 3 * n * T0 * KEV_TO_J });
  const rafRef = useRef(null);

  const reset = useCallback(() => {
    stateRef.current = { t: 0, W: 3 * n * T0 * KEV_TO_J };
    setData([{ t: 0, T: T0, Pfus: 0, Pext: heatingMW, Ptransport: 0, Pbrem: 0 }]);
  }, [n, T0, heatingMW]);

  useEffect(() => { reset(); }, [n, tau, volume, heatingMW, T0]); // eslint-disable-line

  useEffect(() => {
    if (!running) return;
    const Pext = () => (heatingMW * 1e6) / volume;
    const substepsPerFrame = 12;
    const dt = 0.02;
    function frame() {
      let { t, W } = stateRef.current;
      for (let i = 0; i < substepsPerFrame; i++) {
        W = rk4Step(t, W, dt, n, tau, Pext);
        t += dt;
      }
      stateRef.current = { t, W };
      const T = Math.max(W / (3 * n * KEV_TO_J), 1e-3);
      const toMW = volume / 1e6;
      setData((d) => {
        const nd = [...d, {
          t: Number(t.toFixed(2)), T,
          Pfus: fusionPowerDensity(n, T) * toMW,
          Pext: (heatingMW * 1e6) / volume * toMW,
          Ptransport: (W / tau) * toMW,
          Pbrem: bremsstrahlungLoss(n, T) * toMW,
        }];
        return nd.length > 600 ? nd.slice(nd.length - 600) : nd;
      });
      if (t < 90) rafRef.current = requestAnimationFrame(frame);
      else setRunning(false);
    }
    rafRef.current = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(rafRef.current);
  }, [running, n, tau, volume, heatingMW]);

  const last = data[data.length - 1] || {};

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
      <Panel title="Reactor Parameters" className="lg:col-span-1">
        <Slider label="Density n" value={n} onChange={setN} min={1e19} max={1e21} unit=" /m³" log />
        <Slider label="Confinement τ" value={tau} onChange={setTau} min={0.01} max={10} unit=" s" log />
        <Slider label="Plasma volume" value={volume} onChange={setVolume} min={1} max={2000} unit=" m³" />
        <Slider label="Heating power" value={heatingMW} onChange={setHeatingMW} min={0} max={200} unit=" MW" />
        <Slider label="Start temp" value={T0} onChange={setT0} min={0.1} max={20} step={0.1} unit=" keV" />
        <div className="flex gap-2 mt-4">
          <button onClick={() => setRunning((r) => !r)}
            className="flex items-center gap-1.5 px-3 py-2 rounded text-sm font-medium"
            style={{ background: running ? C.danger : C.fusion, color: "#0a0c10" }}>
            {running ? <Pause size={14} /> : <Play size={14} />} {running ? "Pause" : "Run"}
          </button>
          <button onClick={reset}
            className="flex items-center gap-1.5 px-3 py-2 rounded text-sm"
            style={{ background: C.grid, color: C.ink, border: `1px solid ${C.panelBorder}` }}>
            <RotateCcw size={14} /> Reset
          </button>
        </div>
      </Panel>

      <Panel title="Live Readout" className="lg:col-span-1">
        <div className="text-xs" style={{ color: C.sub }}>t = {(last.t ?? 0).toFixed(1)} s</div>
        <div className="text-3xl font-bold mt-1" style={{ ...mono, color: C.fusion }}>
          {(last.T ?? T0).toFixed(1)} keV
        </div>
        <div className="text-xs mb-3" style={{ color: C.sub }}>plasma temperature</div>
        <div className="text-xl" style={{ ...mono, color: C.ok }}>{(last.Pfus ?? 0).toFixed(1)} MW</div>
        <div className="text-xs" style={{ color: C.sub }}>fusion power</div>
      </Panel>

      <Panel title="Temperature vs Time" className="lg:col-span-2">
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data}>
            <CartesianGrid stroke={C.grid} />
            <XAxis dataKey="t" stroke={C.sub} tick={{ fontSize: 11 }} label={{ value: "s", position: "insideBottomRight", fill: C.sub, fontSize: 10 }} />
            <YAxis stroke={C.sub} tick={{ fontSize: 11 }} />
            <Tooltip contentStyle={{ background: C.panel, border: `1px solid ${C.panelBorder}` }} labelStyle={{ color: C.ink }} />
            <Line type="monotone" dataKey="T" stroke={C.fusion} dot={false} strokeWidth={2} isAnimationActive={false} name="T (keV)" />
          </LineChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="Power Balance" className="lg:col-span-4">
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={data}>
            <CartesianGrid stroke={C.grid} />
            <XAxis dataKey="t" stroke={C.sub} tick={{ fontSize: 11 }} />
            <YAxis stroke={C.sub} tick={{ fontSize: 11 }} label={{ value: "MW", angle: -90, position: "insideLeft", fill: C.sub, fontSize: 10 }} />
            <Tooltip contentStyle={{ background: C.panel, border: `1px solid ${C.panelBorder}` }} labelStyle={{ color: C.ink }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line type="monotone" dataKey="Pfus" stroke={C.fusion} dot={false} strokeWidth={2} isAnimationActive={false} name="fusion" />
            <Line type="monotone" dataKey="Pext" stroke={C.confine} dot={false} strokeWidth={2} isAnimationActive={false} name="external heating" />
            <Line type="monotone" dataKey="Ptransport" stroke={C.ok} dot={false} strokeWidth={1.5} isAnimationActive={false} name="transport loss" />
            <Line type="monotone" dataKey="Pbrem" stroke={C.danger} dot={false} strokeWidth={1.5} isAnimationActive={false} name="bremsstrahlung" />
          </LineChart>
        </ResponsiveContainer>
      </Panel>
    </div>
  );
}

/* =============================================================================
   VIEW 3 — Miniaturization Sweep (Phase 5, instant recompute)
============================================================================= */
function SizeSweepView() {
  const [chi, setChi] = useState(1.0);
  const [T, setT] = useState(15.0);
  const [B, setB] = useState(12.0);
  const [beta, setBeta] = useState(0.05);
  const [aspect, setAspect] = useState(3.0);
  const [target, setTarget] = useState(0.05);

  const sweep = useMemo(() => {
    const nSizes = 120;
    const aMin = 0.02, aMax = 5.0;
    const pts = [];
    for (let i = 0; i < nSizes; i++) {
      const a = 10 ** (Math.log10(aMin) + (i / (nSizes - 1)) * (Math.log10(aMax) - Math.log10(aMin)));
      const tauE = (a * a) / (4 * chi);
      const n = maxDensityFromBeta(B, T, beta);
      const Q = qFactor(n, T, tauE);
      pts.push({ a, tauE, Q: Q === Infinity ? 1e5 : Q, ignited: Q === Infinity });
    }
    return pts;
  }, [chi, T, B, beta]);

  const breakevenA = sweep.find((p) => p.Q >= 1)?.a;
  const nAtTarget = maxDensityFromBeta(B, T, beta);
  const tauAtTarget = (target * target) / (4 * chi);
  const QAtTarget = qFactor(nAtTarget, T, tauAtTarget);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Panel title="Machine Physics">
        <Slider label="Thermal diffusivity χ" value={chi} onChange={setChi} min={0.01} max={10} unit=" m²/s" log />
        <Slider label="Temperature T" value={T} onChange={setT} min={5} max={50} unit=" keV" />
        <Slider label="Magnetic field B" value={B} onChange={setB} min={1} max={50} unit=" T" />
        <Slider label="Beta limit" value={beta} onChange={setBeta} min={0.01} max={0.15} step={0.005} unit="" />
        <Slider label="Aspect ratio R₀/a" value={aspect} onChange={setAspect} min={1.5} max={5} step={0.1} unit="" />
      </Panel>

      <Panel title="Size vs Fusion Gain" className="lg:col-span-2">
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={sweep}>
            <CartesianGrid stroke={C.grid} />
            <XAxis dataKey="a" scale="log" domain={["auto", "auto"]} type="number"
              stroke={C.sub} tick={{ fontSize: 11 }}
              label={{ value: "minor radius a (m)", position: "insideBottom", offset: -5, fill: C.sub, fontSize: 10 }} />
            <YAxis scale="log" domain={["auto", "auto"]} stroke={C.sub} tick={{ fontSize: 11 }}
              label={{ value: "Q", angle: -90, position: "insideLeft", fill: C.sub, fontSize: 10 }} />
            <Tooltip contentStyle={{ background: C.panel, border: `1px solid ${C.panelBorder}` }} labelStyle={{ color: C.ink }}
              formatter={(v, k) => [typeof v === "number" ? v.toExponential(2) : v, k]} />
            <ReferenceLine y={1} stroke={C.ink} strokeDasharray="4 4" label={{ value: "breakeven", fill: C.ink, fontSize: 10 }} />
            <ReferenceLine x={target} stroke={C.confine} strokeDasharray="2 2" label={{ value: "your target", fill: C.confine, fontSize: 10 }} />
            <Line type="monotone" dataKey="Q" stroke={C.fusion} dot={false} strokeWidth={2.5} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
        <div className="text-xs mt-2" style={{ color: C.sub }}>
          {breakevenA ? `Smallest breakeven radius at these settings: ${breakevenA.toFixed(3)} m` : "No breakeven reached in this range"}
        </div>
      </Panel>

      <Panel title="Target Reactor Size" className="lg:col-span-3">
        <Slider label="Target minor radius" value={target} onChange={setTarget} min={0.02} max={2} unit=" m" log />
        <div className="grid grid-cols-3 gap-4 mt-2">
          <div>
            <div className="text-xs" style={{ color: C.sub }}>Confinement time at this size</div>
            <div className="text-lg" style={{ ...mono, color: C.confine }}>{tauAtTarget.toExponential(2)} s</div>
          </div>
          <div>
            <div className="text-xs" style={{ color: C.sub }}>Max density (beta limit)</div>
            <div className="text-lg" style={{ ...mono, color: C.ink }}>{nAtTarget.toExponential(2)} /m³</div>
          </div>
          <div>
            <div className="text-xs" style={{ color: C.sub }}>Fusion gain Q</div>
            <div className="text-lg font-bold" style={{ ...mono, color: QAtTarget >= 1 ? C.ok : C.danger }}>
              {QAtTarget === Infinity ? "∞" : QAtTarget.toExponential(2)}
            </div>
          </div>
        </div>
      </Panel>
    </div>
  );
}

/* =============================================================================
   VIEW 4 — Radial Profile (Phase 3, computed on demand — heavier PDE solve)
============================================================================= */
function RadialProfileView() {
  const [a, setA] = useState(2.0);
  const [n, setN] = useState(1.0e20);
  const [chi, setChi] = useState(1.0);
  const [heating, setHeating] = useState(8.0);
  const [computing, setComputing] = useState(false);
  const [result, setResult] = useState(null);
  const canvasRef = useRef(null);

  const compute = useCallback(() => {
    setComputing(true);
    setTimeout(() => {
      const res = solveRadialProfile(a, n, chi, 0.1, heating, 0.3, 40);
      setResult(res);
      setComputing(false);
    }, 30);
  }, [a, n, chi, heating]);

  useEffect(() => { compute(); }, []); // eslint-disable-line

  useEffect(() => {
    if (!result || !canvasRef.current) return;
    const ctx = canvasRef.current.getContext("2d");
    const size = 260;
    canvasRef.current.width = size; canvasRef.current.height = size;
    const img = ctx.createImageData(size, size);
    const T = result.T, r = result.r;
    const maxP = Math.max(...T.map((t) => fusionPowerDensity(n, t)), 1e-30);
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const dx = x - size / 2, dy = y - size / 2;
        const rr = (Math.hypot(dx, dy) / (size / 2)) * a;
        let val = 0;
        if (rr <= a) {
          let idx = 0;
          while (idx < r.length - 1 && r[idx + 1] < rr) idx++;
          const Tval = T[idx];
          val = Math.log10(fusionPowerDensity(n, Tval) + 1) / Math.log10(maxP + 1);
        }
        const i = (y * size + x) * 4;
        img.data[i] = Math.min(255, val * 255 * 1.4);
        img.data[i + 1] = Math.min(255, val * 180 * (val > 0.5 ? 1.2 : 0.6));
        img.data[i + 2] = Math.min(255, val * 60);
        img.data[i + 3] = rr <= a ? 255 : 0;
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [result, a, n]);

  const chartData = result
    ? result.r.map((ri, idx) => {
        const row = { r: ri };
        result.snapshots.forEach(([t, T], si) => { row[`t${si}`] = T[idx]; });
        return row;
      })
    : [];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Panel title="Column Parameters">
        <Slider label="Minor radius a" value={a} onChange={setA} min={0.05} max={5} unit=" m" log />
        <Slider label="Density n" value={n} onChange={setN} min={1e19} max={1e21} unit=" /m³" log />
        <Slider label="Thermal diffusivity χ" value={chi} onChange={setChi} min={0.01} max={10} unit=" m²/s" log />
        <Slider label="Heating" value={heating} onChange={setHeating} min={0} max={50} unit=" MW/m" />
        <button onClick={compute} disabled={computing}
          className="w-full mt-2 px-3 py-2 rounded text-sm font-medium"
          style={{ background: C.fusion, color: "#0a0c10", opacity: computing ? 0.5 : 1 }}>
          {computing ? "Solving diffusion..." : "Run to steady state"}
        </button>
        {result && (
          <div className="text-xs mt-3 leading-relaxed" style={{ color: C.sub }}>
            τ_E ≈ {result.tauEst.toExponential(2)} s (from a²/4χ)<br />
            Fusion power: {result.Pfus_MW_per_m.toFixed(2)} MW/m
          </div>
        )}
      </Panel>

      <Panel title="Radial Temperature Profile">
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={chartData}>
            <CartesianGrid stroke={C.grid} />
            <XAxis dataKey="r" stroke={C.sub} tick={{ fontSize: 11 }} label={{ value: "r (m)", position: "insideBottomRight", offset: -5, fill: C.sub, fontSize: 10 }} />
            <YAxis stroke={C.sub} tick={{ fontSize: 11 }} label={{ value: "keV", angle: -90, position: "insideLeft", fill: C.sub, fontSize: 10 }} />
            <Tooltip contentStyle={{ background: C.panel, border: `1px solid ${C.panelBorder}` }} labelStyle={{ color: C.ink }} />
            {result?.snapshots.map((_, si) => (
              <Line key={si} type="monotone" dataKey={`t${si}`} stroke={C.fusion}
                strokeOpacity={0.35 + (0.65 * si) / (result.snapshots.length - 1)}
                dot={false} strokeWidth={1.8} isAnimationActive={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </Panel>

      <Panel title="Cross-Section (brightness = fusion power)">
        <div className="flex justify-center">
          <canvas ref={canvasRef} style={{ width: 220, height: 220, borderRadius: "50%" }} />
        </div>
      </Panel>
    </div>
  );
}

/* =============================================================================
   VIEW 5 — Field Geometry (Phase 4, live canvas render)
============================================================================= */
function FieldGeometryView() {
  const [R0, setR0] = useState(6.2);
  const [a, setA] = useState(2.0);
  const [B0, setB0] = useState(5.3);
  const [Ip, setIp] = useState(15);
  const [rStart, setRStart] = useState(1.0);
  const [angle, setAngle] = useState(0.6);
  const canvasRef = useRef(null);

  const q = safetyFactor(rStart, a, R0, B0, Ip * 1e6);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = 520, H = 420;
    canvas.width = W; canvas.height = H;
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);

    const scale = 30;
    const cx = W / 2, cy = H / 2;
    const proj = (x, y, z) => {
      const rx = x * Math.cos(angle) - y * Math.sin(angle);
      const ry = x * Math.sin(angle) + y * Math.cos(angle);
      return [cx + rx * scale, cy - z * scale - ry * scale * 0.25];
    };

    // torus guide ring
    ctx.strokeStyle = "#333a47"; ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i <= 100; i++) {
      const phi = (i / 100) * 2 * Math.PI;
      const [px, py] = proj(R0 * Math.cos(phi), R0 * Math.sin(phi), 0);
      i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
    }
    ctx.stroke();

    const colors = [C.confine, C.fusion, C.ok];
    [rStart * 0.5, rStart, Math.min(rStart * 1.5, a * 0.95)].forEach((r, idx) => {
      const pts = traceFieldLine(R0, a, B0, Ip * 1e6, r);
      ctx.strokeStyle = colors[idx]; ctx.lineWidth = 1.1; ctx.globalAlpha = 0.85;
      ctx.beginPath();
      pts.forEach(([x, y, z], i) => {
        const [px, py] = proj(x, y, z);
        i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
      });
      ctx.stroke();
    });
    ctx.globalAlpha = 1;
  }, [R0, a, B0, Ip, rStart, angle]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <Panel title="Tokamak Geometry">
        <Slider label="Major radius R₀" value={R0} onChange={setR0} min={1} max={10} unit=" m" />
        <Slider label="Minor radius a" value={a} onChange={setA} min={0.3} max={4} unit=" m" />
        <Slider label="Toroidal field B₀" value={B0} onChange={setB0} min={1} max={20} unit=" T" />
        <Slider label="Plasma current Iₚ" value={Ip} onChange={setIp} min={1} max={20} unit=" MA" />
        <Slider label="Field line start r" value={rStart} onChange={setRStart} min={0.1} max={a} step={0.05} unit=" m" />
        <Slider label="View rotation" value={angle} onChange={setAngle} min={0} max={6.28} step={0.05} unit=" rad" />
        <div className="text-sm mt-2" style={{ ...mono, color: C.ink }}>
          Safety factor q(r) ≈ {q.toFixed(2)}
        </div>
        <div className="text-xs mt-1" style={{ color: C.sub }}>
          q &lt; 1 near the core invites kink instabilities — a real stability boundary.
        </div>
      </Panel>
      <Panel title="Field Line Trace (drag rotation to spin)" className="lg:col-span-2">
        <canvas ref={canvasRef} style={{ width: "100%", maxWidth: 520, display: "block", margin: "0 auto" }} />
      </Panel>
    </div>
  );
}

/* =============================================================================
   MODULE REGISTRY — the plugin architecture. Fusion is module #1; a second
   subject registers here later as {id, name, icon, views:[...]} without
   touching anything above.
============================================================================= */
const MODULES = {
  fusion: {
    id: "fusion", name: "Fusion Reactor", icon: Atom,
    tagline: "Arc-reactor-scale plasma physics",
    views: [
      { id: "triple", name: "Triple Product", icon: Gauge, component: TripleProductView },
      { id: "energy", name: "Energy Balance", icon: Waves, component: EnergyBalanceView },
      { id: "sweep", name: "Size Sweep", icon: Radio, component: SizeSweepView },
      { id: "radial", name: "Radial Profile", icon: Orbit, component: RadialProfileView },
      { id: "field", name: "Field Geometry", icon: Orbit, component: FieldGeometryView },
    ],
  },
};

export default function ArcSimDashboard() {
  const [moduleId, setModuleId] = useState("fusion");
  const mod = MODULES[moduleId];
  const [viewId, setViewId] = useState(mod.views[0].id);
  const view = mod.views.find((v) => v.id === viewId) || mod.views[0];
  const ViewComponent = view.component;

  return (
    <div className="min-h-screen w-full flex" style={{ background: C.bg, color: C.ink }}>
      {/* Module sidebar */}
      <div className="w-56 shrink-0 p-4 flex flex-col gap-1" style={{ borderRight: `1px solid ${C.panelBorder}` }}>
        <div className="flex items-center gap-2 mb-6 px-1">
          <Atom size={20} color={C.fusion} />
          <span className="text-sm font-bold tracking-widest" style={{ ...mono }}>ARC-SIM</span>
        </div>
        <div className="text-xs uppercase tracking-widest mb-2 px-1" style={{ color: C.sub }}>Modules</div>
        {Object.values(MODULES).map((m) => {
          const Icon = m.icon;
          const active = m.id === moduleId;
          return (
            <button key={m.id} onClick={() => { setModuleId(m.id); setViewId(MODULES[m.id].views[0].id); }}
              className="flex items-center gap-2 px-3 py-2 rounded text-sm text-left transition-colors"
              style={{ background: active ? C.panel : "transparent", color: active ? C.ink : C.sub,
                       border: `1px solid ${active ? C.panelBorder : "transparent"}` }}>
              <Icon size={15} color={active ? C.fusion : C.sub} /> {m.name}
            </button>
          );
        })}
        <button disabled
          className="flex items-center gap-2 px-3 py-2 rounded text-sm text-left mt-1 cursor-not-allowed"
          style={{ color: "#454d5b", border: `1px dashed ${C.panelBorder}` }}>
          <Plus size={15} /> Add module
        </button>
        <div className="text-[11px] mt-2 px-3 leading-snug" style={{ color: "#454d5b" }}>
          New subjects register here as independent modules — no changes needed elsewhere.
        </div>
      </div>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="px-6 py-4" style={{ borderBottom: `1px solid ${C.panelBorder}` }}>
          <div className="text-lg font-bold">{mod.name}</div>
          <div className="text-xs" style={{ color: C.sub }}>{mod.tagline}</div>
        </div>
        <div className="flex gap-1 px-6 pt-3" style={{ borderBottom: `1px solid ${C.panelBorder}` }}>
          {mod.views.map((v) => {
            const Icon = v.icon;
            const active = v.id === viewId;
            return (
              <button key={v.id} onClick={() => setViewId(v.id)}
                className="flex items-center gap-1.5 px-3 py-2 text-sm rounded-t"
                style={{ color: active ? C.fusion : C.sub, borderBottom: active ? `2px solid ${C.fusion}` : "2px solid transparent" }}>
                <Icon size={14} /> {v.name}
              </button>
            );
          })}
        </div>
        <div className="flex-1 overflow-auto p-6">
          <ViewComponent />
        </div>
      </div>
    </div>
  );
}
