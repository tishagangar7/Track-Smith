// Entry — boots the app, shows the splash, hands off.
//
// Replace the setTimeout below with a real readiness signal once your backend
// is wired up — e.g. resolve `ready` when your /api/session/init returns.

function Root() {
  const [phase, setPhase] = React.useState('loading'); // 'loading' | 'app'

  React.useEffect(() => {
    if (phase !== 'loading') return;
    // TODO: replace with real backend init call
    const t = setTimeout(() => setPhase('app'), 3200);
    return () => clearTimeout(t);
  }, [phase]);

  // wire these up to your backend
  const handlers = {
    onSend:        (text) => console.log('[send]', text),
    onPlay:        () => console.log('[play]'),
    onStop:        () => console.log('[stop]'),
    onLoop:        () => console.log('[loop]'),
    onAcceptGhost: (id) => console.log('[accept]', id),
    onSkipGhost:   (id) => console.log('[skip]',   id),
    onTweakGhost:  (id) => console.log('[tweak]',  id),
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: TS.bg }}>
      <div style={{
        position: 'absolute', inset: 0,
        opacity: phase === 'app' ? 1 : 0,
        transition: 'opacity 600ms ease',
      }}>
        <App {...handlers} />
      </div>

      {phase === 'loading' && (
        <div style={{
          position: 'absolute', inset: 0,
          animation: 'ts-fade-out 3.2s ease forwards',
        }}>
          <LoadingScreen />
        </div>
      )}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<Root />);
