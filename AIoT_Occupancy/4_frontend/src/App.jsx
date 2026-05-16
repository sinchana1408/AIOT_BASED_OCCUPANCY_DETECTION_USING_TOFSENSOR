import { useState, useEffect, useRef, useCallback } from "react";
import {
  AreaChart, Area, LineChart, Line,
  BarChart, Bar,
  XAxis, YAxis, Tooltip, CartesianGrid,
  ResponsiveContainer, ReferenceLine
} from "recharts";

// ── Design tokens ─────────────────────────────────────────────────────────────
const C = {
  bg:     "#08090d",
  panel:  "#0f1117",
  panel2: "#131620",
  border: "#1e2130",
  accent: "#00e5ff",
  purple: "#7c4dff",
  green:  "#00e676",
  orange: "#ff6b35",
  red:    "#ff1744",
  muted:  "#4a5270",
  text:   "#cdd5f0",
};

const API = "http://127.0.0.1:8000";

// ─────────────────────────────────────────────────────────────────────────────
// HOOK — SSE live stream from FastAPI serial server
// ─────────────────────────────────────────────────────────────────────────────
function useSerialStream(apiBase) {
  const [readings,  setReadings]  = useState([]);
  const [live,      setLive]      = useState(null);
  const [connected, setConnected] = useState(false);
  const [serialInfo, setSerialInfo] = useState({ connected: false, port: null, error: null });
  const esRef  = useRef(null);
  const cntRef = useRef(0);

  const connect = useCallback(() => {
    if (esRef.current) esRef.current.close();

    const es = new EventSource(`${apiBase}/stream`);
    esRef.current = es;

    es.onopen = () => {
      setConnected(true);
      console.log("[SSE] connected");
    };

    es.onerror = () => {
      setConnected(false);
      console.warn("[SSE] connection lost — retrying in 3 s");
      setTimeout(connect, 3000);
    };

    es.onmessage = (e) => {
      const d = JSON.parse(e.data);

      // status-only frame from server
      if (d.type === "connected" || d.type === "status") {
        if (d.serial) setSerialInfo(d.serial);
        return;
      }

      // real sensor reading
      const pt = {
        idx:        cntRef.current++,
        dist:       d.distance_mm,
        count:      d.count,
        occupied:   d.occupied,
        confidence: d.confidence,
        timestamp:  d.timestamp,
      };
      setLive(pt);
      setSerialInfo(prev => ({ ...prev, connected: true }));
      setReadings(prev => [...prev.slice(-80), pt]);
    };
  }, [apiBase]);

  useEffect(() => {
    connect();
    return () => { if (esRef.current) esRef.current.close(); };
  }, [connect]);

  return { readings, live, connected, serialInfo, reconnect: connect };
}

// ─────────────────────────────────────────────────────────────────────────────
// SMALL UI COMPONENTS
// ─────────────────────────────────────────────────────────────────────────────
const Dot = ({ on, color }) => (
  <span style={{
    display:"inline-block", width:9, height:9, borderRadius:"50%",
    background: on ? (color || C.green) : C.muted,
    boxShadow:  on ? `0 0 7px ${color || C.green}` : "none",
    marginRight:6, verticalAlign:"middle",
    animation:  on ? "pulse 1.4s ease infinite" : "none",
  }} />
);

const Card = ({ children, style = {} }) => (
  <div style={{
    background: C.panel, border: `1px solid ${C.border}`,
    borderRadius: 14, padding: "18px 22px", ...style,
  }}>{children}</div>
);

const Label = ({ children }) => (
  <div style={{ color: C.muted, fontSize: 11, textTransform: "uppercase",
                letterSpacing: "0.1em", marginBottom: 8 }}>{children}</div>
);

const KPI = ({ label, value, unit, color }) => (
  <Card style={{ flex: 1, minWidth: 120 }}>
    <Label>{label}</Label>
    <div style={{ color: color || C.text, fontSize: 30,
                  fontFamily: "'JetBrains Mono',monospace",
                  fontWeight: 700, lineHeight: 1 }}>
      {value}
      <span style={{ fontSize: 13, color: C.muted, marginLeft: 4 }}>{unit}</span>
    </div>
  </Card>
);

const Tip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: C.panel2, border: `1px solid ${C.border}`,
                  borderRadius: 8, padding: "8px 14px", fontSize: 12 }}>
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.color || C.text }}>
          {p.name}: {typeof p.value === "number" ? p.value.toFixed(1) : p.value}
        </div>
      ))}
    </div>
  );
};

const PeopleBar = ({ count, max = 3 }) => (
  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
    {Array.from({ length: max }).map((_, i) => (
      <div key={i} style={{
        height: 32, width: 40, borderRadius: 8,
        background:  i < count ? C.purple : C.border,
        boxShadow:   i < count ? `0 0 12px ${C.purple}66` : "none",
        transition:  "all 0.3s ease",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 16,
      }}>
        {i < count ? "👤" : ""}
      </div>
    ))}
    <span style={{ color: C.muted, fontSize: 12 }}>/ {max} capacity</span>
  </div>
);

const ZoneBar = ({ dist }) => {
  const pct  = Math.min(100, (dist / 2000) * 100);
  const col  = dist < 350 ? C.red : dist < 700 ? C.orange : C.green;
  const zone = dist < 350 ? "NEAR" : dist < 700 ? "MID" : "FAR";
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between",
                    fontSize: 11, color: C.muted, marginBottom: 5 }}>
        <span>0 mm</span>
        <span style={{ color: col }}>{zone} ZONE — {Math.round(dist)} mm</span>
        <span>2000 mm</span>
      </div>
      <div style={{ height: 10, background: C.border, borderRadius: 5, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: col,
                      borderRadius: 5, transition: "width 0.4s ease",
                      boxShadow: `0 0 8px ${col}66` }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between",
                    marginTop: 5, fontSize: 10, color: C.muted }}>
        <span style={{ color: C.red   }}>◄ NEAR (0–350)</span>
        <span style={{ color: C.orange }}>MID (350–700) ►</span>
        <span style={{ color: C.green }}>FAR (700+) ►</span>
      </div>
    </div>
  );
};

const HistoryTable = ({ readings }) => {
  const rows = [...readings].reverse().slice(0, 8);
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
      <thead>
        <tr style={{ color: C.muted, borderBottom: `1px solid ${C.border}` }}>
          {["#", "Distance", "Count", "Confidence", "Status"].map(h => (
            <th key={h} style={{ padding: "6px 10px", textAlign: "left", fontWeight: 500 }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} style={{ borderBottom: `1px solid ${C.border}22`,
                               animation: "fadeIn 0.3s ease" }}>
            <td style={{ padding: "7px 10px", color: C.muted, fontFamily: "monospace" }}>{r.idx}</td>
            <td style={{ padding: "7px 10px", fontFamily: "monospace", color: C.text }}>
              {Math.round(r.dist)} mm
            </td>
            <td style={{ padding: "7px 10px", color: C.purple }}>{r.count}</td>
            <td style={{ padding: "7px 10px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ flex: 1, height: 4, background: C.border, borderRadius: 2 }}>
                  <div style={{ width: `${r.confidence * 100}%`, height: "100%",
                                background: r.confidence > 0.7 ? C.green : C.orange,
                                borderRadius: 2 }} />
                </div>
                <span style={{ color: C.text }}>{(r.confidence * 100).toFixed(0)}%</span>
              </div>
            </td>
            <td style={{ padding: "7px 10px" }}>
              <span style={{
                background: r.occupied ? `${C.purple}22` : `${C.muted}18`,
                color:       r.occupied ? C.purple : C.muted,
                borderRadius: 20, padding: "3px 12px", fontSize: 11,
              }}>
                {r.occupied ? "occupied" : "vacant"}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// COM PORT SWITCHER PANEL
// ─────────────────────────────────────────────────────────────────────────────
function ComPanel({ serialInfo, onConnect, onDisconnect, onRefreshPorts }) {
  const [port,  setPort]  = useState("COM4");
  const [baud,  setBaud]  = useState("115200");
  const [ports, setPorts] = useState([]);
  const [msg,   setMsg]   = useState("");

  const fetchPorts = async () => {
    try {
      const r = await fetch(`${API}/com/ports`);
      const d = await r.json();
      setPorts(d.ports || []);
      setMsg(`Found ${d.ports.length} port(s)`);
    } catch {
      setMsg("Cannot reach server");
    }
  };

  const handleConnect = async () => {
    setMsg("Connecting...");
    try {
      const r = await fetch(`${API}/com/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ port, baud: parseInt(baud) }),
      });
      const d = await r.json();
      setMsg(d.serial?.error ? `Error: ${d.serial.error}` : `Connected to ${port}`);
      onConnect?.();
    } catch {
      setMsg("Server unreachable");
    }
  };

  const handleDisconnect = async () => {
    await fetch(`${API}/com/disconnect`, { method: "POST" });
    setMsg("Disconnected");
    onDisconnect?.();
  };

  return (
    <Card style={{ marginBottom: 20 }}>
      <Label>Serial / COM Port</Label>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>

        {/* Port input or dropdown */}
        {ports.length > 0 ? (
          <select value={port} onChange={e => setPort(e.target.value)}
            style={{ background: C.panel2, border: `1px solid ${C.border}`,
                     borderRadius: 8, padding: "9px 12px", color: C.text,
                     fontSize: 13, cursor: "pointer", outline: "none" }}>
            {ports.map(p => (
              <option key={p.device} value={p.device}>
                {p.device} — {p.description}
              </option>
            ))}
          </select>
        ) : (
          <input value={port} onChange={e => setPort(e.target.value)}
            placeholder="COM4"
            style={{ background: C.panel2, border: `1px solid ${C.border}`,
                     borderRadius: 8, padding: "9px 12px", color: C.text,
                     fontSize: 13, width: 110, outline: "none" }} />
        )}

        {/* Baud rate */}
        <select value={baud} onChange={e => setBaud(e.target.value)}
          style={{ background: C.panel2, border: `1px solid ${C.border}`,
                   borderRadius: 8, padding: "9px 10px", color: C.muted,
                   fontSize: 12, cursor: "pointer", outline: "none" }}>
          {["9600","19200","38400","57600","115200"].map(b => (
            <option key={b} value={b}>{b}</option>
          ))}
        </select>

        <button onClick={fetchPorts} style={{
          background: "transparent", border: `1px solid ${C.border}`,
          borderRadius: 8, padding: "9px 14px", color: C.muted,
          fontSize: 12, cursor: "pointer" }}>
          Scan Ports
        </button>

        <button onClick={handleConnect} style={{
          background: C.green, color: "#000", border: "none",
          borderRadius: 8, padding: "9px 20px", fontSize: 13,
          fontWeight: 700, cursor: "pointer" }}>
          Connect
        </button>

        {serialInfo.connected && (
          <button onClick={handleDisconnect} style={{
            background: "transparent", border: `1px solid ${C.red}`,
            borderRadius: 8, padding: "9px 16px", color: C.red,
            fontSize: 12, cursor: "pointer" }}>
            Disconnect
          </button>
        )}

        {/* Status pill */}
        <div style={{
          background: serialInfo.connected ? `${C.green}18` : `${C.red}18`,
          border:     `1px solid ${serialInfo.connected ? C.green : C.red}`,
          borderRadius: 20, padding: "5px 14px", fontSize: 12,
          color: serialInfo.connected ? C.green : C.red,
        }}>
          <Dot on={serialInfo.connected} color={serialInfo.connected ? C.green : C.red} />
          {serialInfo.connected
            ? `${serialInfo.port} connected`
            : serialInfo.error || "Not connected"}
        </div>
      </div>

      {msg && (
        <div style={{ marginTop: 8, color: C.muted, fontSize: 11 }}>{msg}</div>
      )}

      <div style={{ marginTop: 8, color: C.muted, fontSize: 11, lineHeight: 1.6 }}>
        STM32 must print <code style={{ color: C.accent, background: C.panel2,
                                         padding: "1px 6px", borderRadius: 4 }}>
          DIST:423</code> via UART at 115200 baud.&nbsp;
        Default port: <strong style={{ color: C.text }}>COM4</strong> —
        change in <code style={{ color: C.accent }}>3_api_server/server.py</code> line&nbsp;
        <code style={{ color: C.orange }}>DEFAULT_COM_PORT</code>.
      </div>
    </Card>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN APP
// ─────────────────────────────────────────────────────────────────────────────
export default function App() {
  const { readings, live, connected, serialInfo, reconnect }
    = useSerialStream(API);

  const [manualDist,   setManualDist]   = useState("");
  const [manualResult, setManualResult] = useState(null);

  // Stats
  const occPct  = readings.length
    ? Math.round(readings.filter(r => r.occupied).length / readings.length * 100)
    : 0;
  const avgDist = readings.length
    ? Math.round(readings.reduce((s, r) => s + r.dist, 0) / readings.length)
    : 0;
  const maxCnt  = readings.length ? Math.max(...readings.map(r => r.count)) : 0;

  const distrib = [0,1,2,3].map(c => ({
    label: `${c} ppl`,
    count: readings.filter(r => r.count === c).length,
  }));

  const testPredict = async () => {
    if (!manualDist) return;
    try {
      const res  = await fetch(`${API}/predict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ distance_mm: parseFloat(manualDist) }),
      });
      setManualResult(await res.json());
    } catch {
      setManualResult({ error: "Cannot reach server — is  uvicorn  running?" });
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 1300, margin: "0 auto" }}>

      {/* ── Header ── */}
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "flex-start", marginBottom: 24,
                    flexWrap: "wrap", gap: 12 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
            <div style={{ width: 3, height: 30, background: C.accent, borderRadius: 2 }} />
            <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.5px" }}>
              AIoT Occupancy Monitor
            </h1>
          </div>
          <div style={{ color: C.muted, fontSize: 12, paddingLeft: 13 }}>
            <Dot on={connected} color={C.green} />
            {connected ? "SSE stream active" : "Connecting to API..."}
            &nbsp;·&nbsp;
            <Dot on={serialInfo.connected} color={C.accent} />
            {serialInfo.connected
              ? `${serialInfo.port} — VL53L0X live`
              : "Serial not connected"}
            &nbsp;·&nbsp; STM32 B-L4S5I-IOT01A
          </div>
        </div>
        <button onClick={reconnect} style={{
          background: "transparent", border: `1px solid ${C.border}`,
          borderRadius: 8, padding: "8px 16px", color: C.muted,
          fontSize: 12, cursor: "pointer" }}>
          ↺ Reconnect SSE
        </button>
      </div>

      {/* ── COM Port Panel ── */}
      <ComPanel serialInfo={serialInfo} onConnect={reconnect} />

      {/* ── KPIs ── */}
      <div style={{ display: "flex", gap: 12, marginBottom: 20, flexWrap: "wrap" }}>
        <KPI label="Distance"   value={live ? Math.round(live.dist) : "---"} unit="mm"  color={C.accent} />
        <KPI label="Occupants"  value={live?.count ?? 0} unit="ppl"
             color={live?.count > 0 ? C.purple : C.muted} />
        <KPI label="Confidence" value={live ? Math.round(live.confidence * 100) : "---"} unit="%" color={C.green} />
        <KPI label="Occ. Rate"  value={occPct}  unit="%"  color={C.orange} />
        <KPI label="Avg Dist"   value={avgDist || "---"} unit="mm" />
        <KPI label="Total Readings" value={readings.length} unit="" color={C.muted} />
      </div>

      {/* ── Status + Zone ── */}
      <div style={{ display: "flex", gap: 16, marginBottom: 20, flexWrap: "wrap" }}>
        <Card style={{ flex: 2, minWidth: 260 }}>
          <Label>Current Status</Label>
          <div style={{ display: "flex", alignItems: "center",
                        justifyContent: "space-between", flexWrap: "wrap", gap: 14 }}>
            <div>
              <div style={{ fontSize: 28, fontWeight: 700,
                            color: live?.occupied ? C.purple : C.muted,
                            display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                <Dot on={live?.occupied} color={C.purple} />
                {live?.occupied ? "OCCUPIED" : "VACANT"}
              </div>
              <PeopleBar count={live?.count ?? 0} />
            </div>
            <div style={{
              width: 90, height: 90, borderRadius: "50%",
              border:     `4px solid ${live?.occupied ? C.purple : C.border}`,
              display:    "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center",
              boxShadow:  live?.occupied ? `0 0 20px ${C.purple}44` : "none",
              transition: "all 0.5s ease",
            }}>
              <div style={{ fontSize: 32, fontFamily: "'JetBrains Mono',monospace",
                            fontWeight: 700,
                            color: live?.occupied ? C.purple : C.muted }}>
                {live?.count ?? 0}
              </div>
              <div style={{ fontSize: 10, color: C.muted }}>people</div>
            </div>
          </div>
        </Card>

        <Card style={{ flex: 3, minWidth: 280 }}>
          <Label>Distance Zone</Label>
          <ZoneBar dist={live?.dist ?? 1000} />
        </Card>
      </div>

      {/* ── Charts ── */}
      <div style={{ display: "flex", gap: 16, marginBottom: 20, flexWrap: "wrap" }}>
        <Card style={{ flex: 3, minWidth: 280 }}>
          <Label>Distance Stream (mm)</Label>
          <ResponsiveContainer width="100%" height={170}>
            <AreaChart data={readings} margin={{ left: -10, right: 5 }}>
              <defs>
                <linearGradient id="dg1" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor={C.accent} stopOpacity={0.25} />
                  <stop offset="95%" stopColor={C.accent} stopOpacity={0}    />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={C.border} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="idx" hide />
              <YAxis domain={[0, 2100]} tick={{ fill: C.muted, fontSize: 10 }} />
              <Tooltip content={<Tip />} />
              <ReferenceLine y={700} stroke={C.orange} strokeDasharray="4 2" strokeWidth={1} />
              <ReferenceLine y={350} stroke={C.red}    strokeDasharray="4 2" strokeWidth={1} />
              <Area type="monotone" dataKey="dist" name="dist(mm)"
                    stroke={C.accent} fill="url(#dg1)" strokeWidth={2}
                    dot={false} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        <Card style={{ flex: 2, minWidth: 200 }}>
          <Label>People Count</Label>
          <ResponsiveContainer width="100%" height={170}>
            <LineChart data={readings} margin={{ left: -10, right: 5 }}>
              <CartesianGrid stroke={C.border} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="idx" hide />
              <YAxis domain={[0, 4]} ticks={[0,1,2,3]} tick={{ fill: C.muted, fontSize: 10 }} />
              <Tooltip content={<Tip />} />
              <Line type="stepAfter" dataKey="count" name="count"
                    stroke={C.purple} strokeWidth={2.5}
                    dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>

      {/* ── Distribution + History ── */}
      <div style={{ display: "flex", gap: 16, marginBottom: 20, flexWrap: "wrap" }}>
        <Card style={{ flex: 1, minWidth: 200 }}>
          <Label>Occupancy Distribution</Label>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={distrib} margin={{ left: -10, right: 5 }}>
              <CartesianGrid stroke={C.border} strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: C.muted, fontSize: 11 }} />
              <YAxis tick={{ fill: C.muted, fontSize: 10 }} />
              <Tooltip content={<Tip />} />
              <Bar dataKey="count" name="samples" fill={C.purple} radius={[4,4,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card style={{ flex: 3, minWidth: 280, overflow: "auto" }}>
          <Label>Recent Readings</Label>
          <HistoryTable readings={readings} />
        </Card>
      </div>

      {/* ── Manual Test ── */}
      <Card>
        <Label>Manual Predict (test without board)</Label>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <input
            type="number"
            placeholder="Distance in mm  e.g. 423"
            value={manualDist}
            onChange={e => setManualDist(e.target.value)}
            onKeyDown={e => e.key === "Enter" && testPredict()}
            style={{ background: C.panel2, border: `1px solid ${C.border}`,
                     borderRadius: 8, padding: "10px 14px", color: C.text,
                     fontSize: 14, width: 250, outline: "none" }}
          />
          <button onClick={testPredict} style={{
            background: C.accent, color: "#000", border: "none",
            borderRadius: 8, padding: "10px 24px",
            fontSize: 13, fontWeight: 700, cursor: "pointer" }}>
            PREDICT
          </button>
          {manualResult && (
            <div style={{ background: C.panel2, border: `1px solid ${C.border}`,
                          borderRadius: 8, padding: "10px 16px", fontSize: 13,
                          fontFamily: "'JetBrains Mono',monospace",
                          color: manualResult.error ? C.red : C.green,
                          animation: "fadeIn 0.3s ease" }}>
              {manualResult.error
                ? manualResult.error
                : `occupied=${String(manualResult.occupied)}  count=${manualResult.count}  conf=${(manualResult.confidence*100).toFixed(0)}%`}
            </div>
          )}
        </div>
        <div style={{ marginTop: 8, color: C.muted, fontSize: 11 }}>
          Calls POST {API}/predict — also pushed to the live stream above
        </div>
      </Card>

      {/* Footer */}
      <div style={{ marginTop: 20, textAlign: "center", color: C.muted, fontSize: 11 }}>
        B-L4S5I-IOT01A · VL53L0X ToF · USB Serial COM4 · RF + GBR · FastAPI + React
      </div>
    </div>
  );
}
