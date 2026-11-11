# duck-to-api Design Direction

Design Read:
Reading this as: Developer operations console with a visual image test bench for technical operators, in an industrial utilitarian style, dial ENERGY 1 / RHYTHM 2 / MOTION 1.

## Identity & Header
- Brand header: plain typographic wordmark `duck-to-api` in monospace bold (`18px`), paired with live server and browser status indicators. No graphic logo or decorative icon beside the title (R-23).
- Theme support: working Light and Dark mode toggle persisted in `localStorage` (`duck_to_api_theme`), defaulting to Dark for long-running console monitoring with full Light parity (R-21, R-34).

## Color Palette (2 core neutrals + 1 deliberate accent)
All pairs verified via `contrast-check.py` to exceed WCAG AA 4.5:1 for normal text and 3.0:1 for UI boundaries (R-25, R-29):

### Light Theme
- Canvas (`--bg-canvas`): `#F5F6F8`
- Surface (`--bg-surface`): `#FFFFFF`
- Subtle surface (`--bg-subtle`): `#ECEEF2`
- Border (`--border`): `#D0D5DD`
- Text primary (`--text-primary`): `#111418` (18.47:1 on `#FFFFFF`)
- Text secondary (`--text-secondary`): `#475467` (7.69:1 on `#FFFFFF`, 6.62:1 on `#ECEEF2`)
- Accent (`--accent`): `#B45309` (warm industrial amber; `#FFFFFF` on `#B45309` = 5.02:1)
- Accent hover (`--accent-hover`): `#92400E`
- Status semantic pairs:
  - OK: `#15803D` on `#DCFCE7` (4.57:1)
  - Error: `#B91C1C` on `#FEE2E2` (5.30:1)
  - Warning / Needs Auth: `#854D0E` on `#FEF9C3` (6.38:1)

### Dark Theme
- Canvas (`--bg-canvas`): `#0D1117`
- Surface (`--bg-surface`): `#161B22`
- Subtle surface (`--bg-subtle`): `#1F2630`
- Border (`--border`): `#30363D`
- Text primary (`--text-primary`): `#F0F6FC` (17.39:1 on `#0D1117`, 15.89:1 on `#161B22`)
- Text secondary (`--text-secondary`): `#9AA4B2` (7.50:1 on `#0D1117`, 6.86:1 on `#161B22`)
- Accent (`--accent`): `#F59E0B` (`#111418` ink on `#F59E0B` = 8.60:1; `#F59E0B` text on `#161B22` = 8.05:1)
- Accent hover (`--accent-hover`): `#D97706`
- Status semantic pairs:
  - OK: `#86EFAC` on `#052E16` (10.62:1)
  - Error: `#FCA5A5` on `#450A0A` (8.51:1)
  - Warning / Needs Auth: `#FDE047` on `#422006` (11.06:1)

## Typography & Layout Rhythm
- UI font stack: `"Segoe UI Variable", "Segoe UI", system-ui, -apple-system, sans-serif` for clean native legibility without render-blocking external font requests (R-06, R-40).
- Code, IDs, logs, and API snippets: `"Cascadia Mono", "Consolas", ui-monospace, monospace`.
- Radii: crisp `6px` on panels and inputs, `4px` on buttons and status tags, never all-pill shapes (R-11).
- Elevation: flat surfaces with `1px` structural borders; shadow reserved strictly for the image lightbox modal when inspecting full-resolution outputs (R-12).
- Layout rhythm (RHYTHM 2):
  1. Top operational bar (`duck-to-api`, browser runtime state, single-click Manual Login / Headless mode actions, theme toggle, navigation tabs).
  2. Primary workspace split by operator workflow:
     - **Operations & Queue view**: Browser session controls + compact live queue metrics + filterable Jobs & History table with input/output thumbnails, error diagnostics, retry/cancel actions, and real-time SSE log console.
     - **Playground & Output Gallery view**: Two-column bench pairing prompt/image upload form + generated `curl` API snippet on the left with a spacious side-by-side Input vs Output visual preview stage and clickable Output Gallery grid below.
     - **Adapters & API Reference view**: Registered site adapters, live capability flags, and verified local OpenAI-compatible + Job endpoints.
- Motion (MOTION 1): Subtle hover/focus state transitions (`120ms`) only; zero decorative looping pulses or entrance animations, honoring `prefers-reduced-motion: reduce` (R-19, R-39).
