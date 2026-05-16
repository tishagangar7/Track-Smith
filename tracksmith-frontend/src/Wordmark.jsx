// <Wordmark /> — locked logo (wave-under)
// Props:
//   size         — wordmark text height, in px (default 32)
//   color        — primary color (default TS.fg)
//   accent       — accent color used for the "transient" bars (default TS.amber)
//   compact      — true → smaller wave under the text (use in app bars)
//   accentIndex  — center of the highlighted bar cluster (0–63)
function Wordmark({ size = 32, color, accent, compact = false, accentIndex = 26 }) {
  const c = color  || TS.fg;
  const a = accent || TS.amber;
  const waveH = compact ? size * 0.32 : size * 0.42;
  const gap   = size * 0.14;

  return (
    <div style={{
      display: 'inline-flex',
      flexDirection: 'column',
      alignItems: 'stretch',
      gap,
      lineHeight: 1,
    }}>
      <div style={{
        fontFamily: TS.font,
        fontWeight: 700,
        fontSize: size,
        letterSpacing: -size * 0.045,
        color: c,
      }}>
        tracksmith
      </div>
      <svg viewBox="0 0 360 28" width="100%" height={waveH} preserveAspectRatio="none">
        {Array.from({ length: 64 }).map((_, i) => {
          const v = Math.abs(Math.sin(i * 0.42) + Math.sin(i * 0.13) * 0.6) / 1.5;
          const h = 4 + v * 22;
          const isAccent = i >= accentIndex - 4 && i <= accentIndex + 4;
          return (
            <rect
              key={i}
              x={i * 5.6}
              y={14 - h / 2}
              width="3"
              height={h}
              rx="1.5"
              fill={isAccent ? a : c}
              opacity={isAccent ? 1 : 0.92}
            />
          );
        })}
      </svg>
    </div>
  );
}
window.Wordmark = Wordmark;
