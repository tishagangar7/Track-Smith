// <LoadingScreen /> — splash + live agent-pipeline status.
// Props:
//   steps   — [{ t: 'parsing reference', state: 'done' | 'active' | 'pending' }]
//   meta    — e.g. "v0.4 · session #f9 · A min · 88 bpm"
//
// Hook into your backend by streaming the steps array as the agent advances.
function LoadingScreen({
  steps = [
    { t: 'parsing reference',   state: 'done' },
    { t: 'picking key + tempo', state: 'done' },
    { t: 'drafting blocks',     state: 'active' },
    { t: 'wiring the graph',    state: 'pending' },
  ],
  meta = 'v0.4 · session #f9 · A min · 88 bpm',
}) {
  return (
    <div style={{
      width: '100%', height: '100%',
      background: TS.bg, color: TS.fg, fontFamily: TS.font,
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      gap: 36, position: 'relative', overflow: 'hidden',
    }}>
      {/* soft amber glow behind the vinyl */}
      <div style={{
        position: 'absolute',
        width: 700, height: 700, borderRadius: '50%',
        background: `radial-gradient(${TS.amber}33, transparent 60%)`,
        filter: 'blur(20px)',
        top: '-20%', left: '50%', transform: 'translateX(-50%)',
        pointerEvents: 'none',
      }} />

      <VinylSpinner size={170} speed={2.4} />

      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
        <Wordmark size={62} />
        <div style={{
          fontSize: 13, color: TS.dim,
          letterSpacing: 1.4, textTransform: 'uppercase',
        }}>
          make music with an agent
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 6 }}>
        {steps.map((s, i) => (
          <React.Fragment key={s.t}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                width: 8, height: 8, borderRadius: 999,
                background: s.state === 'done'   ? TS.amber
                          : s.state === 'active' ? TS.amber
                          : TS.line,
                opacity:   s.state === 'pending' ? 0.5 : 1,
                boxShadow: s.state === 'active' ? `0 0 12px ${TS.amber}` : 'none',
              }} />
              <div style={{
                fontSize: 12,
                color: s.state === 'done'   ? TS.dim
                     : s.state === 'active' ? TS.fg
                     : TS.dim2,
              }}>{s.t}</div>
            </div>
            {i < steps.length - 1 && <div style={{ width: 18, height: 1, background: TS.line }} />}
          </React.Fragment>
        ))}
      </div>

      <div style={{
        position: 'absolute', bottom: 28,
        fontSize: 11, color: TS.dim2,
        letterSpacing: 1.4, textTransform: 'uppercase',
      }}>
        {meta}
      </div>
    </div>
  );
}
window.LoadingScreen = LoadingScreen;
