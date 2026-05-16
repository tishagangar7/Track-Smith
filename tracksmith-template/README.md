# tracksmith — frontend

The final UI template, broken into clean components and ready to wire to your backend.

## Run it

Just open `index.html` in a browser — no build step. It uses React + Babel from a CDN so you can iterate quickly.

For production: copy the JSX into a Vite/Next project and remove the Babel `<script>` from `index.html`.

## File map

```
index.html                  ← entry HTML, loads the scripts in order
src/
  tokens.jsx                ← design tokens (colors, fonts) → window.TS
  Wordmark.jsx              ← <Wordmark/> — the locked logo (wave-under)
  VinylSpinner.jsx          ← <VinylSpinner/> — brand loading indicator
  LoadingScreen.jsx         ← <LoadingScreen/> — splash w/ agent pipeline
  App.jsx                   ← <App/> — chat panel + node canvas
  main.jsx                  ← entry, splash → app transition
```

## Wiring the backend

`<App/>` takes the following props — pass real data and callbacks once you
have endpoints:

| Prop            | Shape |
|-----------------|-------|
| `session`       | `{ name, bpm, key, agentOn }` |
| `messages`      | `[{ id, who: 'you' \| 'agent', text, refs?: [nodeId], ghostId? }]` |
| `nodes`         | `[{ id, label, sub, x, y, w, h, color, bars }]` |
| `ghostNodes`    | `[{ id, label, sub, x, y, w, h, color }]` — pending agent suggestions |
| `edges`         | `[[srcId, dstId, 'solid' \| 'ghost']]` |
| `isRendering`   | `bool` — toggles the small spinning vinyl in the transport bar |
| `onSend(text)`  | user typed a prompt |
| `onPlay/Stop/Loop()` | transport |
| `onAcceptGhost(id)` / `onSkipGhost(id)` / `onTweakGhost(id)` | agent suggestion actions |

`<LoadingScreen/>` takes a `steps` array (`done` / `active` / `pending`) — stream
that from your agent's status as it spins up.

In `main.jsx`, the splash currently hides after a `setTimeout` — replace with
your actual readiness signal (e.g. `await fetch('/api/session/init')`).
