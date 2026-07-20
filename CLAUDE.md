# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AgriSage — an AI-based crop disease diagnosis service. A photo of a leaf goes in; an LLM explains the diagnosis, recommends treatment personalized to the user, and follows up after treatment. Currently a Flask app serving a static, mobile-first frontend; there is no real backend yet — auth, crop storage, diagnosis, and history are all mocked client-side in `frontend/js/store.js` (localStorage + a random `mockDiagnose()`). See "Personalization & mock data" below before touching any of the post-login screens.

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
                      link straight to index.html (the old, simpler guest home).
  login.html         Login form + social-login button stubs. Submit redirects
                      to dashboard.html. Link to signup.html. No real auth.
  signup.html        Email/password + certification (conventional/organic) and
                      default purpose (self_consumption/sale) radios. These are
                      the account-level personalization variables — saved via
                      saveProfile(). Submit redirects to dashboard.html.
  dashboard.html      Home screen for logged-in users. Lists registered crops
                      (from getCrops()), a follow-up-pending banner (from
                      getHistory()), and a "Diagnose" CTA pre-filled with the
                      most recently registered crop.
  crop-select.html   Register a crop: pick from 14 crops, then set
                      growing_environment (open_field/greenhouse), a per-crop
                      purpose override, and expected harvest date. Saved via
                      addCrop(). Shows the list of already-registered crops.
  diagnose.html       Photo upload (with photo-quality tips) for a specific
                      crop (?cropId=...). Runs mockDiagnose(), stashes the
                      result in sessionStorage, redirects to
                      diagnosis-result.html.
  diagnosis-result.html  Reads the pending diagnosis from sessionStorage.
                      Traffic-light banner (🟢/🟡/🔴 — see logic below),
                      explanation ("Cause & Explanation" card), personalized
                      treatment recommendations with an "other options
                      considered" accordion, and a PHI banner when the crop's
                      resolved purpose is "sale". Also reachable in read-only
                      mode from history.html (sessionStorage payload has
                      `viewOnly: true` and skips re-adding a history entry).
  follow-up.html      3-checkbox post-treatment check-in for one history
                      entry (?id=...). All checked -> "stopped progressing"
                      message; any unchecked -> "consult an expert" message.
                      Updates that history entry's `followUpStatus`.
  history.html        Past diagnoses (getHistory()). Clicking one re-enters
                      diagnosis-result.html in view-only mode.
  mypage.html         Edit account personalization fields (same UI as
                      signup.html), manage registered crops (edit/delete,
                      reusing crop-select.html's fields inline), and a
                      notifications toggle.
  index.html          Guest-only simple home screen (no login, no crops) —
                      reachable only via landing.html's "Continue as guest".
                      Not part of the logged-in flow; its top nav's Home tab
                      still points to itself, not dashboard.html.
  js/store.js          Shared mock backend: localStorage-backed profile/crops
                      /history (getProfile/saveProfile, getCrops/addCrop/
                      removeCrop/saveCrops, getHistory/addHistoryEntry/
                      updateHistoryEntry/findHistoryEntry, resolvePurpose),
                      plus mockDiagnose() returning one of a few canned
                      results. Included via <script src="js/store.js"> before
                      each page's own inline script. Replace these functions
                      with real fetch() calls once the API below exists —
                      keep the function names/shapes the same so page code
                      doesn't need to change.
  src/input.css       Tailwind entry point (@tailwind directives + a small
                      @layer components block — see "Styling" below)
  css/styles.css       Build output of `npm run build` — gitignored, not
                      committed. Must exist for the pages to be styled.
  tailwind.config.js   Theme: custom color palette (including the traffic-
                      light colors caution/caution-soft/danger/danger-soft),
                      font, spinner keyframes.
  package.json          Scripts: build (one-off), watch (rebuild on save).
render.yaml         Render deploy config — points at backend/, mirrors the
                    gunicorn command above, and also runs the frontend
                    npm install + build so styles.css exists at deploy time.
```

**Path convention**: `backend/app.py` resolves `frontend/` relative to its own
file location (`BASE_DIR/frontend`), not the process CWD, so the app works
whether started from the repo root or from inside `backend/`.

**Screen flow**: `landing.html` (entry, "/") -> `login.html` / `signup.html`
-> `dashboard.html` (home) -> `crop-select.html` (register a crop) ->
`diagnose.html` (upload photo for a specific crop) -> `diagnosis-result.html`
(traffic-light diagnosis + explanation + treatment) -> `follow-up.html`
(post-treatment check-in). `history.html` lists past diagnoses and re-enters
`diagnosis-result.html` in read-only mode. `mypage.html` edits the account
and crop list. `index.html` is a separate, simpler guest-only home reachable
via landing's "Continue as guest" — it is not wired into the logged-in flow
above. Pages link with plain `<a href>` / `window.location.href` and pass
state via URL query params (`crop`, `color`, `emoji`, `cropId`, history `id`)
or, for the diagnosis payload (which includes the uploaded image data URL),
via `sessionStorage["agrisage_pending_diagnosis"]`. There is no client-side
router.

**Navigation**: `dashboard.html`, `crop-select.html`, `diagnose.html`,
`diagnosis-result.html`, `follow-up.html`, `history.html`, and `mypage.html`
all share the same top `<header>` — a logo row plus a Home/Diagnose/History/
Profile tab row (`sticky top-0`), where Home points to `dashboard.html`.
Except on `dashboard.html` itself, there's also a back-arrow + page-title row
underneath, inside the same `<header>`. `landing.html`, `login.html`,
`signup.html`, and `index.html` are outside the logged-in flow and don't use
this header (`login.html`/`signup.html` only have a small back arrow). When
adding a page to the logged-in flow, copy the shared header block rather than
inventing a different nav pattern; there used to be a bottom nav bar on
`index.html` only — that was deliberately moved into the header and made
consistent, so don't reintroduce a bottom nav.

**Personalization & mock data**: the three personalization variables are
`certification` (conventional/organic, account-level, set in `signup.html`),
`growing_environment` (open_field/greenhouse, per-crop, set in
`crop-select.html`), and `purpose` (self_consumption/sale, account-level
default in `signup.html`, overridable per crop in `crop-select.html`/
`mypage.html`). Use `resolvePurpose(crop, profile)` from `store.js` to get
the effective purpose for a crop — never read `crop.purposeOverride` or
`profile.purpose` directly. **Confidence gate**: in `diagnosis-result.html`,
`confidence < 70` always yields the 🟡 "uncertain" state (disease name and
recommendations are hidden; an expert-consult message shows instead),
regardless of severity. Otherwise `severity === "very high"` yields 🔴
(urgent), and anything else is 🟢. Don't reorder these checks.

**Frontend/backend boundary**: everything under "Personalization & mock
data" above is currently backed by `frontend/js/store.js`, not a real
backend. The candidate real API shape (not implemented) is:
```
POST /api/signup   POST /api/login   POST /api/crops   GET /api/crops
POST /api/diagnose { image, crop_id } -> { class_id, confidence, severity }  (placeholder exists, 501)
POST /api/explain  { class_id, user_profile } -> { symptoms, cause, recommendations, exclusion_reasons }
POST /api/follow-up  GET /api/history
```
When wiring these in, replace the bodies of `store.js`'s functions with
`fetch()` calls and keep their names/return shapes so the page scripts don't
need to change. `backend/app.py` only has `POST /api/diagnose` so far
(returns 501), backed by code that should live under `backend/models/`.

**Styling**: all visual styling is Tailwind utility classes written directly
in the HTML `class="..."` attributes — there are no more page-level `<style>`
blocks and no other CSS framework. The only custom CSS lives in
`frontend/src/input.css`, and it's intentionally minimal: `@tailwind`
directives plus an `@layer components` block for a handful of classes the
inline `<script>` tags toggle via `classList` at runtime (`.crop-card.selected`,
`.next-btn.ready` / `.primary-btn.ready`, `.result.show`, `.spinner.show`,
`.icon-btn` / `.back-btn`). These exist only because Tailwind utilities can't
be conditionally added/removed by class name the way plain CSS classes can.
Newer pages (dashboard/diagnosis-result/follow-up/history/mypage) don't add
more classes here — their JS-driven show/hide states just toggle Tailwind's
built-in `hidden` utility directly (`el.classList.toggle("hidden")`), which
is the preferred pattern for any new dynamic state; only reach for a new
`@layer components` entry if plain utility toggling genuinely can't express
it. Everything else stays as inline utility classes, not new custom CSS.
The color palette — `page`, `app`, `ink`, `muted`, `accent`, `accent-dark`,
`accent-soft`, `card`, `border`, `warn` (general warning banners, e.g. PHI),
plus `caution`/`caution-soft` (🟡) and `danger`/`danger-soft` (🔴) for the
diagnosis traffic light — is defined once in `frontend/tailwind.config.js`;
use those names instead of hardcoding hex values in new markup.

## Structure is intentional — keep it

`backend/` (server + model) and `frontend/` (static pages, Tailwind-styled)
are deliberately separate so the model can be developed and deployed
independently of the UI. Do not flatten this back into a single directory,
do not move the model code anywhere other than `backend/models/`, and do not
reintroduce per-page `<style>` blocks, a different CSS framework, or a
different build tool for the frontend — Tailwind CLI via `frontend/package.json`
is the one build path, and `render.yaml` / `scripts/setup.*` all assume it.
