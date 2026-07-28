# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AgriSage — an AI-based crop disease diagnosis service. A photo of a leaf goes in;
the backend detects the leaf, classifies the disease with a trained CNN, looks the
class up in a structured knowledge base, and has an LLM (OpenAI GPT) explain the
diagnosis and recommend treatment personalized to the user, with a follow-up
check after treatment. A Flask app serves both the static, mobile-first frontend
and the diagnosis API. The **diagnosis flow is fully wired frontend-to-backend**;
auth, crop storage, and history are still deliberately mocked client-side in
`frontend/js/store.js` (localStorage) — see "Frontend/backend boundary" below
before touching any of the post-login screens.

## Commands

Setup (creates `.venv`, installs backend deps, installs frontend npm deps, and
builds the Tailwind CSS once):
```bash
./scripts/setup.sh          # macOS / Linux
./scripts/setup.ps1         # Windows (PowerShell)
```

Run the dev server. Two env vars point at the classifier checkpoint — without
them the pipeline falls back to a mock 42%-confidence prediction that always
lands in the "uncertain" path (useful for UI work without the model):
```bash
MODEL_CHECKPOINT_PATH=backend/models/weights/classification_model.pth \
MODEL_CONFIG_PATH=backend/models/config6.json \
python backend/app.py       # http://localhost:5000
```
Relative `MODEL_*` paths are resolved against the repo root (see
`_resolve_path` in `backend/ai/pipeline.py`), so they work regardless of CWD.
On the primary dev machine use conda `env1`'s python
(`/home/kntst/anaconda3/envs/env1/bin/python` — has torch + cv2); see
`backend/models/CLAUDE.md`.

LLM credentials: put `OPENAI_API_KEY` in a `.env` at the repo root or in
`backend/.env` (python-dotenv searches parent dirs; see `backend/.env.example`).
Optional overrides: `OPENAI_MODEL` (default `gpt-4o-mini`),
`OPENAI_EMBEDDING_MODEL` (default `text-embedding-3-small`).

Run as it runs in production (Google Cloud Run — a container built from the
repo-root `Dockerfile`):
```bash
gunicorn --chdir backend --workers 1 --timeout 120 --bind 0.0.0.0:$PORT app:app
```
The `Dockerfile` is multi-stage: a Node stage builds the Tailwind CSS, then a
Python stage installs **CPU-only torch first** (the default PyPI wheel bundles
CUDA and is far too large for the image), then `backend/requirements.txt`, and
copies the built frontend in. Cloud Run injects `$PORT` (8080) and gunicorn
binds to it. `MODEL_CHECKPOINT_PATH`/`MODEL_CONFIG_PATH` are baked into the
image as `ENV`; `OPENAI_API_KEY` must be supplied at deploy time and is never
committed. **Production deploys via Cloud Run's GitHub continuous deployment**:
in the Cloud Run console, connect this repo with Build Type "Dockerfile" (region
`us-central1`), set `OPENAI_API_KEY` under Variables & Secrets (the `MODEL_*`
paths are baked into the image), and every push to the connected branch triggers
a Cloud Build + redeploy — no local Docker or `gcloud` needed.
`./scripts/deploy-cloudrun.sh` (wrapping `gcloud run deploy --source .`) remains
a one-off CLI alternative — export `OPENAI_API_KEY` in your shell first.

Quick public demo from a dev machine (no Cloud Run): run the dev server, then
`cloudflared tunnel --url http://localhost:5000` — gives a temporary public
HTTPS URL (HTTPS is required for the camera capture feature).

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
  app.py           Entry point. "/" serves frontend/landing.html; "/<path>"
                    serves any other frontend/* file. API routes:
                    - POST /api/diagnose  (implemented): multipart form
                      {image (jpg/jpeg/png, ≤10MB), crop_id, user_input,
                      harvest_date, certification, growing_environment,
                      purpose}. Saves the upload to backend/uploads/, runs
                      ai.pipeline.diagnose(), persists via db.crud, returns
                      the result dict + diagnosis_id. pipeline errors are
                      caught and returned as a friendly 500 JSON.
                    - POST /api/diagnose/<id>/ask: free-text follow-up Q&A
                      via RAG semantic search + GPT (diagnosis_id is accepted
                      but not yet used for context).
                    - GET /api/history: all stored diagnoses (global — no
                      user scoping; the UI intentionally doesn't use it yet).
  ai/              RAG + LLM diagnosis pipeline (no Flask, no DB).
    pipeline.py     diagnose(image_path, profile, user_input, harvest_date):
                    (1) leaf detection via models/leaf_detect (wrapped so it
                        can never crash the pipeline; falls back to the
                        original image), (2) classify_image() — lazily loads
                        the checkpoint from MODEL_CHECKPOINT_PATH, else mock
                        ("Potato___Late_blight", 42.0), (3) KB exact-match
                        lookup by class_id, (4) confidence gate <70 →
                        "uncertain" BEFORE the is_healthy check (order is
                        load-bearing — a low-confidence "healthy" must not
                        reassure), (5) severity from the KB entry →
                        traffic_light "urgent" iff "very high", (6) GPT
                        understanding-level classification + explanation,
                        plus pls.py's rule-based product/PHI suggestion.
                    Class names come from a classes.json next to the
                    checkpoint (or MODEL_CLASSES_PATH) so inference does not
                    need the training dataset on disk.
    llm/client.py   OpenAI SDK wrapper: generate_text (json_mode adds a
                    system message + response_format json_object),
                    generate_json (fence-tolerant), embed_text,
                    get_embedding_model(). Lazy client; clear error if
                    OPENAI_API_KEY is missing.
    llm/explain.py  KB-grounded explanation prompt (falls back to raw KB
                    fields on any LLM failure). llm/level_classifier.py
                    (Beginner/Intermediate/Advanced from user_input),
                    llm/chat.py (Q&A over RAG results), llm/pls.py (pure
                    regex/heuristic PHI + product hint — no LLM).
    rag/store.py    Deterministic class_id lookup over the 38-entry KB JSON
                    (rag/data/AgriSage_Disease_Knowledge_Base_EN.json).
    rag/search.py   Semantic search (used ONLY by /ask): embeds all entries,
                    caches vectors to rag/data/embeddings_cache.json tagged
                    with the embedding model name — old-format or
                    wrong-model caches re-embed automatically.
  db/              SQLite persistence (backend/db/agrisage.db, gitignored).
    models.py       Schema + init_db() (called at app import): diagnoses,
                    follow_up_reminders (reminders are still unwired).
    crud.py         save_diagnosis, get_history, get_due_follow_ups /
                    mark_follow_up_sent (the last two have no callers yet).
  models/          Full training/inference codebase (GoogLeNet + ViT on
                    PlantVillage) — see backend/models/CLAUDE.md.
    leaf_detect.py  Torch-free leaf detection module used by the pipeline
                    (and by predict_leaf.py): ExG Otsu mask → hole fill →
                    GrabCut fallback → connected components → nearest-to-
                    center leaf (fragmented leaves re-merged, leaf clusters
                    split by a gated watershed) → GrabCut refinement that
                    grows the box over discolored/diseased tissue → square
                    256×256 **letterboxed** crop. Returns both `bbox` (the
                    square the classifier saw — may extend outside the photo)
                    and `leaf_bbox` (tight box around the leaf, always
                    inside — this is what the UI overlays). Images are loaded
                    with EXIF transpose so coordinates match the browser's
                    displayed orientation. Tuning here is measured against a
                    labeled real-photo set — see backend/models/CLAUDE.md
                    before changing any gate, the pad, or the fill color.
    weights/        classification_model.pth — slimmed GoogLeNet_6
                    checkpoint-epoch4 (38MB: state_dict + arch/epoch meta,
                    no optimizer/ConfigParser), THE one committed exception
                    to the "no *.pth in git" rule (needed for deploys) —
                    plus classes.json (12 prepared6 classes).
  uploads/         Runtime upload dir (gitignored): originals + the
                    <stem>_leaf.jpg crops. No cleanup job yet.
  requirements.txt  flask, gunicorn, openai>=2.0, python-dotenv, numpy,
                    torch/torchvision (CPU wheels in prod), pillow,
                    opencv-python-headless.
frontend/           Static HTML + Tailwind CSS, no JS framework.
  landing.html        Entry page ("/"). "Log in" CTA -> login.html, plus
                      "Continue as guest" -> index.html.
  login.html         Email/password form only. No real auth — submit
                      redirects to dashboard.html.
  signup.html        Adds certification (conventional/organic) and default
                      purpose (self_consumption/sale) radios, saved via
                      saveProfile(). Redirects to dashboard.html.
  dashboard.html      Home for logged-in users: crops (getCrops()), a
                      follow-up-pending banner (skips entries whose
                      followUpStatus is set, incl. "not_needed"), Diagnose CTA.
  crop-select.html   Register a crop: 3 crops (Apple, Grape, Tomato —
                      matching the deployed 12-class model's coverage),
                      growing_environment, per-crop purpose override,
                      expected harvest date.
  diagnose.html       Photo input for a specific crop (?cropId=...) with TWO
                      paths: in-page camera (getUserMedia live preview →
                      shutter → canvas → JPEG blob; falls back to a native
                      capture input) and gallery upload (accept jpeg/png
                      only — the backend rejects other formats). Preview is
                      object-contain (whole photo visible). Optional
                      user-notes textarea is sent as user_input. Submits via
                      store.js diagnoseWithApi() (REAL API call) with an
                      inline error state; on success stashes the payload in
                      sessionStorage and opens diagnosis-result.html.
  diagnosis-result.html  Renders the API result by status: healthy (green,
                      new state), uncertain (yellow, expert-consult copy),
                      diagnosed (disease card + GPT action list + product
                      recommendation; urgent/red via traffic_light or
                      severity "very high"). Legacy results without a status
                      field fall back to the original confidence<70 gate.
                      Shows an "Analyzed Photo" card with the leaf bounding
                      box overlaid (percent-positioned from
                      result.leafDetection.leaf_bbox, falling back to .bbox
                      for older stored results — server coordinates are
                      EXIF-upright so they align with the displayed image).
                      All LLM/API strings go through esc() before innerHTML.
                      On first render it writes a history entry (healthy/
                      uncertain entries get followUpStatus "not_needed") and
                      flips the sessionStorage payload to viewOnly so a
                      refresh doesn't duplicate history.
  follow-up.html      3-checkbox post-treatment check-in for one history
                      entry (?id=...). Sets followUpStatus resolved/escalate.
  history.html        Past diagnoses (localStorage). Re-enters
                      diagnosis-result.html read-only, preferring the full
                      stored entry.result over the legacy placeholder.
  mypage.html         Edit account personalization + manage crops.
  index.html          Guest-only simple home (unchanged, still mock-only).
  js/store.js          localStorage-backed profile/crops/history (getProfile/
                      saveProfile, getCrops/addCrop/removeCrop/saveCrops,
                      getHistory/addHistoryEntry/updateHistoryEntry/
                      findHistoryEntry, resolvePurpose), escapeHtml(), and
                      the REAL diagnosis call: diagnoseWithApi() builds
                      FormData (normalized ASCII filename — the backend's
                      secure_filename strips non-ASCII names) and
                      mapDiagnosisResponse() converts the API shape to the
                      same result shape mockDiagnose() returns (+ status,
                      trafficLight, actions, diagnosisId, leafDetection).
                      mockDiagnose() is kept for reference but is no longer
                      called by any page.
  src/input.css       Tailwind entry point (see "Styling").
  css/styles.css       Build output — gitignored, must be rebuilt.
  tailwind.config.js   Theme incl. traffic-light colors caution/danger.
  manifest.webmanifest / sw.js / js/pwa.js   PWA wiring (see below).
  icons/               PWA icons, generated from icons/icon.svg (the source
                      of truth) via a one-off `sharp` script — regenerate
                      rather than editing the PNGs by hand.
Dockerfile          Cloud Run container: Node stage builds the Tailwind CSS,
                    Python stage installs CPU torch + backend/requirements.txt
                    and copies the built frontend. Bakes
                    MODEL_CHECKPOINT_PATH/MODEL_CONFIG_PATH as ENV (pointing
                    at the committed weights/config6) and runs gunicorn bound
                    to $PORT. OPENAI_API_KEY is supplied at deploy time.
.dockerignore       Keeps the build context small (excludes .venv,
                    node_modules, generated CSS, uploads, the SQLite db, and
                    .env) — but NOT the committed model weights.
scripts/
  deploy-cloudrun.sh  Wraps `gcloud run deploy --source .` (Cloud Build builds
                    the Dockerfile — no local Docker). Reads OPENAI_API_KEY
                    from the shell; SERVICE/REGION overridable via env.
```

**Path convention**: `backend/app.py` resolves `frontend/` relative to its own
file location (`BASE_DIR/frontend`), not the process CWD, and
`backend/ai/pipeline.py` resolves relative `MODEL_*` env paths against the
repo root — the app works whether started from the repo root, from inside
`backend/`, or via `gunicorn --chdir backend`.

**Screen flow**: `landing.html` (entry, "/") -> `login.html` / `signup.html`
-> `dashboard.html` (home) -> `crop-select.html` (register a crop) ->
`diagnose.html` (camera or gallery photo for a specific crop) ->
`diagnosis-result.html` (traffic light + analyzed photo w/ leaf bbox + GPT
explanation + treatment) -> `follow-up.html` (post-treatment check-in).
`history.html` lists past diagnoses and re-enters `diagnosis-result.html` in
read-only mode. `mypage.html` edits the account and crop list. `index.html`
is a separate guest-only home reachable via landing's "Continue as guest".
Pages link with plain `<a href>` / `window.location.href` and pass state via
URL query params (`crop`, `color`, `emoji`, `cropId`, history `id`) or, for
the diagnosis payload (image data URL + mapped result), via
`sessionStorage["agrisage_pending_diagnosis"]`. There is no client-side
router.

**Navigation**: the logged-in pages (`dashboard`, `crop-select`, `diagnose`,
`diagnosis-result`, `follow-up`, `history`, `mypage`) all share the same top
`<header>` — logo row plus Home/Diagnose/History/Profile tabs (`sticky
top-0`), Home -> `dashboard.html`. Except on `dashboard.html` there's also a
back-arrow + page-title row inside the same `<header>`. When adding a page to
the logged-in flow, copy the shared header block; don't reintroduce a bottom
nav.

**Personalization & the confidence gate**: the three personalization
variables are `certification` (account-level), `growing_environment`
(per-crop), and `purpose` (account default, per-crop override) — always read
the effective purpose via `resolvePurpose(crop, profile)`, never
`crop.purposeOverride` or `profile.purpose` directly. The **confidence gate
is enforced server-side** in `pipeline.py`: `confidence < 70` returns status
"uncertain" BEFORE the healthy check (a low-confidence "healthy" must not
reassure the user); severity "very high" makes traffic_light "urgent".
`diagnosis-result.html` trusts `result.status` when present and only applies
the legacy client-side `confidence < 70` gate to old/mock results that lack
one. Don't reorder either gate.

**Frontend/backend boundary** — current reality:
- Implemented and wired: `POST /api/diagnose` (the whole diagnosis flow),
  `POST /api/diagnose/<id>/ask` (backend only — no UI yet),
  `GET /api/history` (backend only — the UI intentionally keeps history in
  localStorage so visitors of the public demo don't see each other's
  records; the server DB is global and unauthenticated).
- Still mocked in `store.js` (deliberate — there is no auth/user model yet):
  signup/login, crop CRUD, the history list UI, and follow-up state.
  Candidate endpoints: `POST /api/signup`, `POST /api/login`,
  `POST/GET /api/crops`, `POST /api/follow-up`. When adding them, replace
  the corresponding `store.js` function bodies with `fetch()` calls and keep
  the function names/return shapes so page code doesn't change —
  `diagnoseWithApi()`/`mapDiagnosisResponse()` are the pattern to follow.

**Model weights policy**: `*.pth` files are never committed — with exactly
one exception, `backend/models/weights/classification_model.pth` (38MB;
state_dict + arch/epoch meta, no optimizer/ConfigParser), which deploys need. Full training checkpoints stay outside
git (see `backend/models/CLAUDE.md` and `backend/models/.gitignore`).

**Styling**: all visual styling is Tailwind utility classes written directly
in the HTML `class="..."` attributes — no page-level `<style>` blocks, no
other CSS framework. The only custom CSS lives in `frontend/src/input.css`
(`@tailwind` directives + a small `@layer components` block for classes the
inline scripts toggle: `.crop-card.selected`, `.cat-tab.active`,
`.preset-btn.active`, `.next-btn.ready` / `.primary-btn.ready`,
`.result.show`, `.spinner.show`, `.icon-btn` / `.back-btn`). New dynamic show/hide states toggle Tailwind's `hidden` utility
directly (`el.classList.toggle("hidden")`) — the camera panel, error banners,
photo card, and leaf bbox overlay all follow this pattern; only reach for a
new `@layer components` entry if plain utility toggling genuinely can't
express it. The color palette (`page`, `app`, `ink`, `muted`, `accent`,
`accent-dark`, `accent-soft`, `card`, `border`, `warn`, plus
`caution`/`caution-soft` (🟡) and `danger`/`danger-soft` (🔴)) is defined once
in `frontend/tailwind.config.js`; use those names instead of hardcoding hex
values in new markup.

**Hybrid app/web (PWA)**: every page has the same PWA boilerplate — manifest
link, icon links, `apple-mobile-web-app-*` meta tags, and
`<script src="js/pwa.js"></script>` right before `</body>`. `sw.js` precaches
every HTML page plus `css/styles.css` and `js/store.js`; HTML *and* CSS/JS
are all network-first (cache fallback only when offline) — deliberate, don't
change it back to cache-first (it caused stale-CSS confusion during
development). Only icons/manifest are cache-first. If you add, rename, or
remove a precached file, update `PRECACHE_URLS` in `sw.js` and bump
`CACHE_NAME` in the same file. When adding a new HTML page, copy the exact
PWA block from an existing page. Note: camera
capture (getUserMedia) requires a secure context — HTTPS or localhost.

## Structure is intentional — keep it

`backend/` (server + AI + model) and `frontend/` (static pages,
Tailwind-styled) are deliberately separate so the model can be developed and
deployed independently of the UI. Do not flatten this back into a single
directory, do not move model code out of `backend/models/` or AI pipeline
code out of `backend/ai/`, and do not reintroduce per-page `<style>` blocks,
a different CSS framework, or a different frontend build tool — Tailwind CLI
via `frontend/package.json` is the one build path, and the `Dockerfile` /
`scripts/setup.*` all assume it. Likewise, don't drop the PWA
manifest/service-worker wiring from a page or introduce a second, native-app
codebase — this is deliberately one static site that works as both web and
installable app.
