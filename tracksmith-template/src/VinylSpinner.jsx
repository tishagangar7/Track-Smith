// <VinylSpinner /> — the brand loading indicator.
// Use anywhere we need a "thinking / loading" signal.
// Props:
//   size   — px (default 120)
//   color  — vinyl color (default TS.fg)
//   label  — center-label grooves color (default TS.bgWarm)
//   accent — center label color (default TS.amber)
//   speed  — seconds per rotation (default 2.4)
function VinylSpinner({ size = 120, color, label, accent, speed = 2.4 }) {
  const c = color  || TS.fg;
  const lb = label || TS.bgWarm;
  const a  = accent || TS.amber;

  return (
    <div style={{
      width: size,
      height: size,
      position: 'relative',
      animation: `ts-vinyl-spin ${speed}s linear infinite`,
      transformOrigin: '50% 50%',
    }}>
      <svg viewBox="0 0 100 100" width={size} height={size}>
        <circle cx="50" cy="50" r="48" fill={c} />
        {[44, 40, 36, 32, 28, 24, 20].map(rr => (
          <circle key={rr} cx="50" cy="50" r={rr} fill="none" stroke={lb} strokeOpacity="0.18" strokeWidth="0.6" />
        ))}
        <path d="M 14 50 a 36 36 0 0 1 36 -36" stroke={lb} strokeOpacity="0.08" strokeWidth="6" fill="none" />
        <circle cx="50" cy="50" r="15" fill={a} />
        <circle cx="50" cy="50" r="2.2" fill={lb} />
        <rect x="49" y="34" width="2" height="3" fill={lb} opacity="0.45" />
      </svg>
    </div>
  );
}
window.VinylSpinner = VinylSpinner;
