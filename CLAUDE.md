# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AgriSage — an AI-based crop disease diagnosis service. A photo of a leaf goes in, a diagnosis, cause, and treatment recommendation come out. Currently a Flask app serving a static, mobile-first frontend; the diagnosis model is not yet wired in. Login has no real backend yet — `login.html`'s form just redirects to `index.html`.

## Commands

Setup (creates `.venv`, installs backend deps, installs frontend npm deps, and
builds the Tailwind CSS once):
```bash
./scripts/setup.sh          # macOS / Linux
./scripts/setup.ps1         # Windows (PowerShell)
```

Run the dev server:
```bash
python backend/app.py       # http://localhost:5000
```

Run as it runs in production (Render):
```bash
gunicorn --chdir backend app:app
```

Frontend CSS build (Tailwind CLI, run from `frontend/`):
```bash
npm run build      # one-off build -> frontend/css/styles.css
npm run watch       # rebuild on save; keep running while editing HTML/CSS
```
`frontend/css/styles.css` is generated and gitignored — after pulling changes
or editing any `class="..."` in the HTML or `frontend/src/input.css`, it must
be rebuilt (`npm run build`/`watch`) before the page will look right. There is
no other build step, test suite, or linter in this repo yet.

## Architecture

```
backend/           Flask app — serves frontend/ as static files, hosts the API
  app.py           Entry point. "/" serves frontend/landing.html (the entry
                    page); "/<path>" serves any other frontend/* file.
                    POST /api/diagnose is the placeholder entry point for the
                    diagnosis model (currently returns 501 not_implemented).
  requirements.txt
  models/           Empty — where diagnosis model code/weights will go.
                     Model weights should NOT be committed; see models/README.md.
frontend/           Static HTML + Tailwind CSS, no JS framework.
  landing.html        Entry page ("/"). Intro/marketing content with a
                      "Log in" CTA -> login.html, and a "Continue as guest"
                      link straight to index.html.
  login.html         Login form. Submit redirects to index.html; no real
                      auth is wired up yet. Back arrow returns to landing.html.
  index.html         Home screen
  crop-select.html   Crop picker (14 crops)
  diagnose.html       Photo upload -> diagnosis result (currently mock data)
  src/input.css       Tailwind entry point (@tailwind directives + a small
                      @layer components block — see "Styling" below)
  css/styles.css       Build output of `npm run build` — gitignored, not
                      committed. Must exist for the pages to be styled.
  tailwind.config.js   Theme: custom color palette, font, spinner keyframes.
  package.json          Scripts: build (one-off), watch (rebuild on save).
render.yaml         Render deploy config — points at backend/, mirrors the
                    gunicorn command above, and also runs the frontend
                    npm install + build so styles.css exists at deploy time.
```

**Path convention**: `backend/app.py` resolves `frontend/` relative to its own
file location (`BASE_DIR/frontend`), not the process CWD, so the app works
whether started from the repo root or from inside `backend/`.

**Screen flow**: `landing.html` (entry page, "/") -> `login.html` (form,
reached via the "Log in" CTA; also skippable via "Continue as guest") ->
`index.html` (home) -> `crop-select.html` (crop chosen, passed via query
params) -> `diagnose.html` (upload photo, show AI result). Each page links to
the next with a plain `<a href>` / `window.location.href` — there is no
client-side router.

**Navigation**: `index.html`, `crop-select.html`, and `diagnose.html` all
share the same top `<header>` — a logo row plus a Home/Diagnose/History/
Profile tab row (`sticky top-0`). `crop-select.html` and `diagnose.html`
additionally have a back-arrow + page-title row underneath, inside the same
`<header>`. `landing.html` and `login.html` are pre-login screens and don't
have this header/nav — `login.html` only has a small back arrow to
`landing.html`. When adding a new page after login, copy the shared header
block rather than inventing a different nav pattern; there used to be a
bottom nav bar on `index.html` only — that was deliberately moved into the
header and made consistent across pages, so don't reintroduce a bottom nav.

**Frontend/backend boundary**: frontend pages are static and currently use
mock data in `diagnose.html` for the diagnosis result. When wiring in a real
model, the intended integration point is `POST /api/diagnose` in
`backend/app.py`, backed by code under `backend/models/`.

**Styling**: all visual styling is Tailwind utility classes written directly
in the HTML `class="..."` attributes — there are no more page-level `<style>`
blocks and no other CSS framework. The only custom CSS lives in
`frontend/src/input.css`, and it's intentionally minimal: `@tailwind`
directives plus an `@layer components` block for the handful of classes the
inline `<script>` tags toggle via `classList` at runtime (`.crop-card.selected`,
`.next-btn.ready` / `.primary-btn.ready`, `.result.show`, `.spinner.show`,
`.icon-btn` / `.back-btn`). These exist only because Tailwind utilities can't
be conditionally added/removed by class name the way plain CSS classes can —
everything else should stay as inline utility classes, not new custom CSS.
The color palette (`page`, `app`, `ink`, `muted`, `accent`, `accent-dark`,
`accent-soft`, `card`, `border`, `warn`) is defined once in
`frontend/tailwind.config.js`; use those names instead of hardcoding hex
values in new markup.

## Structure is intentional — keep it

`backend/` (server + model) and `frontend/` (static pages, Tailwind-styled)
are deliberately separate so the model can be developed and deployed
independently of the UI. Do not flatten this back into a single directory,
do not move the model code anywhere other than `backend/models/`, and do not
reintroduce per-page `<style>` blocks, a different CSS framework, or a
different build tool for the frontend — Tailwind CLI via `frontend/package.json`
is the one build path, and `render.yaml` / `scripts/setup.*` all assume it.
