// <App /> — main tracksmith UI: chat panel (left) + node canvas (right).
//
// PROPS — wire these to your backend:
//   session    { name, bpm, key, agentOn }
//   messages   [{ id, who: 'you' | 'agent', text, refs?: [nodeId], ghostId? }]
//   nodes      [{ id, label, sub, x, y, w, h, color, bars }]
//   ghostNodes [{ id, label, sub, x, y, w, h, color }]   // pending agent suggestions
//   edges      [[srcId, dstId, kind]]                    // kind: 'solid' | 'ghost'
//   onSend(text)                  — user typed a prompt
//   onAcceptGhost(id) / onSkipGhost(id) / onTweakGhost(id)
//   onPlay() / onStop() / onLoop()
//
// All props have safe defaults so the file renders on its own.
function App({
  session = { name: 'moonlit drive', bpm: 88, key: 'A min', agentOn: true },
  messages = [
    { id: 1, who: 'you',   text: 'i want a moody synthwave intro, 88 bpm, a minor' },
    { id: 2, who: 'agent', text: 'Sketched four blocks: drums, sub bass, analog pad, and a sparse lead. Connected the bass and drums for sidechain. See the canvas →', refs: ['drums','bass','pad','lead'] },
    { id: 3, who: 'you',   text: 'add something atmospheric between the pad and lead' },
    { id: 4, who: 'agent', text: 'Proposing a vocal-chop layer on a tape delay send. Pinned as a ghost node — accept to insert.', ghostId: 'vox' },
  ],
  nodes = [
    { id: 'drums', label: 'Drums',      sub: 'four-on-the-floor', x: 60,  y: 70,  w: 178, h: 96, color: TS.amber, bars: 8 },
    { id: 'bass',  label: 'Sub bass',   sub: 'sidechain → drums', x: 320, y: 180, w: 178, h: 96, color: TS.amber, bars: 8 },
    { id: 'pad',   label: 'Analog pad', sub: 'Am7 → Dm9',         x: 60,  y: 310, w: 178, h: 96, color: TS.teal,  bars: 16 },
    { id: 'lead',  label: 'Lead motif', sub: 'sparse · 4 notes',  x: 580, y: 70,  w: 178, h: 96, color: TS.plum,  bars: 8 },
    { id: 'glue',  label: 'Glue bus',   sub: 'tape + plate',      x: 580, y: 310, w: 178, h: 96, color: TS.sage,  bars: null },
  ],
  ghostNodes = [
    { id: 'vox', label: 'Vocal chop', sub: 'A4 · tape delay send', x: 320, y: 340, w: 178, h: 84, color: TS.plum },
  ],
  edges = [
    ['drums','bass','solid'], ['drums','glue','solid'], ['bass','glue','solid'],
    ['pad','lead','solid'], ['lead','glue','solid'], ['pad','glue','solid'],
    ['pad','vox','ghost'], ['vox','lead','ghost'],
  ],
  isRendering = true,
  onSend, onPlay, onStop, onLoop,
  onAcceptGhost, onSkipGhost, onTweakGhost,
}) {
  const byId = Object.fromEntries([...nodes, ...ghostNodes].map(n => [n.id, n]));
  const c = (n) => ({ x: n.x + n.w / 2, y: n.y + n.h / 2 });

  return (
    <div style={{
      width: '100%', height: '100%',
      background: TS.bg, color: TS.fg, fontFamily: TS.font,
      display: 'flex', overflow: 'hidden',
    }}>

      {/* ───────────── LEFT — chat ───────────── */}
      <div style={{
        width: 440, borderRight: `1px solid ${TS.line}`,
        display: 'flex', flexDirection: 'column',
      }}>
        {/* brand header */}
        <div style={{
          padding: '20px 22px 16px',
          borderBottom: `1px solid ${TS.line}`,
          display: 'flex', alignItems: 'flex-end', gap: 14,
        }}>
          <Wordmark size={22} compact />
          <div style={{
            marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8,
            fontSize: 11, color: TS.dim, paddingBottom: 4,
          }}>
            <div style={{
              width: 6, height: 6, borderRadius: 999,
              background: session.agentOn ? TS.amber : TS.dim2,
              boxShadow: session.agentOn ? `0 0 8px ${TS.amber}` : 'none',
            }} />
            agent {session.agentOn ? 'on' : 'off'}
          </div>
        </div>

        {/* session pill */}
        <div style={{ padding: '14px 22px 0' }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 8,
            padding: '5px 10px 5px 8px', borderRadius: 999,
            background: TS.panel, border: `1px solid ${TS.line}`,
          }}>
            <div style={{
              width: 14, height: 14, borderRadius: 4,
              background: `linear-gradient(135deg, ${TS.amber}, ${TS.teal})`,
            }} />
            <div style={{ fontSize: 11.5, color: TS.fg }}>{session.name}</div>
            <div style={{ fontSize: 11, color: TS.dim }}>· {session.bpm} bpm · {session.key}</div>
          </div>
        </div>

        {/* messages */}
        <div style={{
          flex: 1, padding: '18px 22px',
          display: 'flex', flexDirection: 'column', gap: 18,
          overflow: 'auto',
        }}>
          {messages.map(m => (
            <div key={m.id} style={{
              display: 'flex', flexDirection: 'column', gap: 6,
              alignItems: m.who === 'you' ? 'flex-end' : 'flex-start',
            }}>
              <div style={{
                fontSize: 10, color: TS.dim2,
                letterSpacing: 0.6, textTransform: 'uppercase',
              }}>{m.who === 'you' ? 'you' : 'agent'}</div>

              <div style={{
                background: m.who === 'you' ? 'transparent' : TS.panel,
                border:     m.who === 'you' ? `1px solid ${TS.line}` : 'none',
                padding: '11px 14px', borderRadius: 12,
                fontSize: 13.5, lineHeight: 1.5, maxWidth: 340,
              }}>{m.text}</div>

              {m.refs && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                  {m.refs.map(rid => {
                    const n = byId[rid]; if (!n) return null;
                    return (
                      <div key={rid} style={{
                        display: 'flex', alignItems: 'center', gap: 6,
                        fontSize: 11, color: TS.dim,
                        padding: '4px 9px', borderRadius: 999,
                        border: `1px solid ${TS.line}`,
                      }}>
                        <div style={{ width: 6, height: 6, borderRadius: 999, background: n.color }} />
                        {n.label}
                      </div>
                    );
                  })}
                </div>
              )}

              {m.ghostId && (
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  <button onClick={() => onAcceptGhost && onAcceptGhost(m.ghostId)} style={btnPrimary}>accept</button>
                  <button onClick={() => onTweakGhost  && onTweakGhost (m.ghostId)} style={btnGhost}>tweak</button>
                  <button onClick={() => onSkipGhost   && onSkipGhost  (m.ghostId)} style={btnGhost}>skip</button>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* composer */}
        <ChatComposer onSend={onSend} />
      </div>

      {/* ───────────── RIGHT — canvas ───────────── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {/* transport */}
        <div style={{
          display: 'flex', alignItems: 'center',
          padding: '14px 24px', borderBottom: `1px solid ${TS.line}`,
          gap: 14,
        }}>
          <div style={{ display: 'flex', gap: 6 }}>
            <button onClick={onPlay} style={iconBtn(true)}>▶</button>
            <button onClick={onStop} style={iconBtn(false)}>◼</button>
            <button onClick={onLoop} style={iconBtn(false)}>↻</button>
          </div>
          <div style={{ fontSize: 13, color: TS.dim, fontVariantNumeric: 'tabular-nums' }}>
            bar 5 / 32 · 00:00:14
          </div>

          {isRendering && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 16 }}>
              <VinylSpinner size={18} accent={TS.teal} speed={3.2} />
              <div style={{ fontSize: 11.5, color: TS.dim }}>rendering preview…</div>
            </div>
          )}

          <div style={{
            marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14,
            fontSize: 12, color: TS.dim,
          }}>
            <span>
              <b style={{ color: TS.fg, fontWeight: 500 }}>{nodes.length}</b> blocks
              {' · '}
              <b style={{ color: TS.fg, fontWeight: 500 }}>{ghostNodes.length}</b> pending
            </span>
            <div style={{ height: 16, width: 1, background: TS.line }} />
            <ViewTabs />
          </div>
        </div>

        {/* node canvas */}
        <div style={{
          flex: 1, position: 'relative', overflow: 'hidden',
          backgroundImage: `radial-gradient(rgba(255,240,210,0.06) 1px, transparent 1px)`,
          backgroundSize: '24px 24px',
        }}>
          {/* edges */}
          <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
            {edges.map(([a, b, kind], i) => {
              const A = byId[a], B = byId[b];
              if (!A || !B) return null;
              const pA = c(A), pB = c(B);
              const dx = (pB.x - pA.x) * 0.4;
              const d = `M ${pA.x} ${pA.y} C ${pA.x + dx} ${pA.y}, ${pB.x - dx} ${pB.y}, ${pB.x} ${pB.y}`;
              const ghost = kind === 'ghost';
              return <path key={i} d={d}
                stroke={ghost ? TS.amber : TS.lineStrong}
                strokeWidth={1.5}
                strokeDasharray={ghost ? '4 5' : '0'}
                fill="none"
                opacity={ghost ? 0.85 : 1}
              />;
            })}
          </svg>

          {nodes.map(n => <Node key={n.id} n={n} />)}
          {ghostNodes.map(n => (
            <GhostNode
              key={n.id}
              n={n}
              onAccept={() => onAcceptGhost && onAcceptGhost(n.id)}
              onSkip={() => onSkipGhost && onSkipGhost(n.id)}
            />
          ))}

          <ZoomControls />
          <AddBar />
        </div>
      </div>
    </div>
  );
}

// ─── chat composer ─────────────────────────────────────────────────────────
function ChatComposer({ onSend }) {
  const [v, setV] = React.useState('');
  return (
    <div style={{ padding: 16, borderTop: `1px solid ${TS.line}` }}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!v.trim()) return;
          onSend && onSend(v.trim());
          setV('');
        }}
        style={{
          background: TS.panel, borderRadius: 12,
          padding: '12px 14px',
          display: 'flex', alignItems: 'center', gap: 10,
        }}
      >
        <div style={{ width: 16, height: 16, borderRadius: 4, border: `1.5px solid ${TS.dim}` }} />
        <input
          value={v}
          onChange={(e) => setV(e.target.value)}
          placeholder="ask, hum, or drop a reference…"
          style={{
            flex: 1, background: 'transparent', border: 'none', outline: 'none',
            color: TS.fg, fontFamily: 'inherit', fontSize: 13.5,
          }}
        />
        <div style={{
          fontSize: 10, color: TS.dim2,
          padding: '4px 7px', borderRadius: 5, border: `1px solid ${TS.line}`,
        }}>⌘K</div>
      </form>
    </div>
  );
}

// ─── node ──────────────────────────────────────────────────────────────────
function Node({ n }) {
  return (
    <div style={{
      position: 'absolute', left: n.x, top: n.y, width: n.w, height: n.h,
      background: TS.nodeBg, borderRadius: 12, border: `1px solid ${TS.line}`,
      padding: '11px 13px', display: 'flex', flexDirection: 'column', gap: 6,
      boxShadow: '0 4px 18px rgba(0,0,0,0.35)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{ width: 7, height: 7, borderRadius: 999, background: n.color }} />
        <div style={{ fontSize: 13, fontWeight: 600 }}>{n.label}</div>
        {n.bars != null && (
          <div style={{
            marginLeft: 'auto', fontSize: 10, color: TS.dim2,
            padding: '2px 6px', border: `1px solid ${TS.line}`, borderRadius: 4,
          }}>{n.bars} bars</div>
        )}
      </div>
      <div style={{ fontSize: 11, color: TS.dim }}>{n.sub}</div>
      <svg viewBox="0 0 100 18" style={{ width: '100%', height: 22, marginTop: 'auto' }} preserveAspectRatio="none">
        {Array.from({ length: 36 }).map((_, i) => {
          const h = 3 + Math.abs(Math.sin(i * 1.7 + n.x * 0.013)) * 12;
          return <rect key={i} x={i * 2.8} y={9 - h / 2} width={1.7} height={h} fill={n.color} opacity={0.85} />;
        })}
      </svg>
    </div>
  );
}

// ─── ghost (pending) node ──────────────────────────────────────────────────
function GhostNode({ n, onAccept, onSkip }) {
  return (
    <div style={{
      position: 'absolute', left: n.x, top: n.y, width: n.w, height: n.h,
      background: 'rgba(232,162,104,0.06)', borderRadius: 12,
      border: `1.5px dashed ${TS.amber}`,
      padding: '10px 13px', display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <div style={{ width: 7, height: 7, borderRadius: 999, background: TS.amber }} />
        <div style={{ fontSize: 13, fontWeight: 600 }}>{n.label}</div>
        <div style={{
          marginLeft: 'auto', fontSize: 9, color: TS.amber,
          padding: '2px 6px', border: `1px solid ${TS.amber}`, borderRadius: 4,
          letterSpacing: 0.5, textTransform: 'uppercase',
        }}>pending</div>
      </div>
      <div style={{ fontSize: 11, color: TS.dim }}>{n.sub}</div>
      <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
        <button onClick={onAccept} style={{ ...btnPrimary, fontSize: 11, padding: '4px 10px' }}>accept</button>
        <button onClick={onSkip}   style={{ ...btnGhost,   fontSize: 11, padding: '4px 10px' }}>skip</button>
      </div>
    </div>
  );
}

// ─── canvas chrome ─────────────────────────────────────────────────────────
function ZoomControls() {
  return (
    <div style={{
      position: 'absolute', right: 18, bottom: 18,
      background: TS.panel, borderRadius: 10, padding: 4,
      display: 'flex', flexDirection: 'column', gap: 2,
      border: `1px solid ${TS.line}`,
    }}>
      {['+', '−', '⊡'].map((g, i) => (
        <div key={i} style={{
          width: 30, height: 30,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 13, color: TS.dim, borderRadius: 6,
        }}>{g}</div>
      ))}
    </div>
  );
}
function AddBar() {
  return (
    <div style={{
      position: 'absolute', left: 18, bottom: 18,
      background: TS.panel, borderRadius: 10, padding: 4,
      display: 'flex', gap: 2, border: `1px solid ${TS.line}`,
    }}>
      {['＋ block', 'edge', 'note'].map((g, i) => (
        <div key={g} style={{
          padding: '7px 12px', borderRadius: 6, fontSize: 11.5,
          color: i === 0 ? TS.fg : TS.dim,
          background: i === 0 ? TS.nodeBg : 'transparent',
        }}>{g}</div>
      ))}
    </div>
  );
}
function ViewTabs() {
  return (
    <div style={{ display: 'flex', gap: 4 }}>
      {['canvas', 'arrange', 'mix'].map((t, i) => (
        <div key={t} style={{
          padding: '5px 10px', borderRadius: 6, fontSize: 11,
          background: i === 0 ? TS.panel : 'transparent',
          border:     i === 0 ? `1px solid ${TS.line}` : 'none',
          color:      i === 0 ? TS.fg : TS.dim,
        }}>{t}</div>
      ))}
    </div>
  );
}

// ─── button styles ─────────────────────────────────────────────────────────
const btnPrimary = {
  fontSize: 12, padding: '6px 13px', borderRadius: 8,
  background: TS.amber, color: '#1a120a',
  fontWeight: 500, border: 'none', cursor: 'pointer',
  fontFamily: 'inherit',
};
const btnGhost = {
  fontSize: 12, padding: '6px 13px', borderRadius: 8,
  background: 'transparent', color: TS.dim,
  border: `1px solid ${TS.line}`, cursor: 'pointer',
  fontFamily: 'inherit',
};
const iconBtn = (primary) => ({
  width: 32, height: 32, borderRadius: 999,
  background: primary ? TS.amber : 'transparent',
  color:      primary ? '#1a120a' : TS.dim,
  border:     primary ? 'none'    : `1px solid ${TS.line}`,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  fontSize: 12, cursor: 'pointer', fontFamily: 'inherit',
});

window.App = App;
