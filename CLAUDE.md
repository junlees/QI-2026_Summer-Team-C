# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AgriSage — an AI-based crop disease diagnosis service. A photo of a leaf goes in;
the backend detects the leaf, classifies the disease with a trained CNN, looks the
class up in a structured knowledge base, and has an LLM (OpenAI GPT) explain the
diagnosis and recommend treatment personalized to the user, with a follow-up
check after treatment. A Flask app serves both the static, mobile-first frontend
and the API. **Everything is wired frontend-to-backend**: JWT signup/login,
server-stored profiles/crops/diagnosis history, the diagnosis flow with a
per-user daily limit (default 3/day), and an admin dashboard (account seeded
from `ADMIN_ID`/`ADMIN_PASSWORD` env) for viewing users/usage and adjusting
limits. `frontend/js/store.js` is the fetch layer — see "Frontend/backend
boundary" below.

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

Secrets: put `OPENAI_API_KEY`, `JWT_SECRET` (token signing — generate with
`python -c "import secrets; print(secrets.token_hex(32))"`; without it the
server warns and uses an insecure dev fallback), and `ADMIN_ID`/`ADMIN_PASSWORD`
(admin account, upserted into the users table at every boot) in a `.env` at the
repo root or in `backend/.env` (python-dotenv searches parent dirs; see
`backend/.env.example`). `app.py` calls `load_dotenv()` explicitly at the very
top — before anything reads the environment. Optional overrides: `OPENAI_MODEL`
(default `gpt-4o-mini`), `OPENAI_EMBEDDING_MODEL` (default
`text-embedding-3-small`).

Run as it runs in production (Google Cloud Run — a container built from the
repo-root `Dockerfile`):
```bash
gunicorn --chdir backend --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT app:app
```
The `Dockerfile` is multi-stage: a Node stage builds the Tailwind CSS, then a
Python stage installs **CPU-only torch first** (the default PyPI wheel bundles
CUDA and is far too large for the image), then `backend/requirements.txt`, and
copies the built frontend in. Cloud Run injects `$PORT` (8080) and gunicorn
binds to it. One worker (the torch model must not be loaded once per process on
a 2Gi instance) with 4 threads, and `OMP_NUM_THREADS=2` so torch doesn't size
its thread pool from the host's core count instead of the container's vCPU
limit. `MODEL_CHECKPOINT_PATH`/`MODEL_CONFIG_PATH` are baked into the image as
`ENV`; `OPENAI_API_KEY` must be supplied at deploy time and is never committed.

**Production deploys via Cloud Run's GitHub continuous deployment.** In the
Cloud Run console: 서비스 만들기 → "저장소에서 지속적 배포" → Cloud Build /
Developer Connect → this GitHub repo → branch → Build Type **Dockerfile**,
source location `/Dockerfile`. The settings that are NOT defaults and that the
service will not run without:

| Console field | Value | Why |
|---|---|---|
| 인증 | 공개 액세스 허용 (allow unauthenticated) | otherwise every request is 403 |
| 리전 | `asia-northeast3` (Seoul) | the console defaults to `europe-west1` |
| 메모리 | **2 GiB** | the 512 MiB default OOM-kills torch on the first diagnosis |
| CPU | 2 | matches the baked `OMP_NUM_THREADS=2` |
| 최대 동시 요청 수 | 4–8 | the default 80 just queues behind one gunicorn worker |
| 요청 시간 초과 | 300s | first request also pays the lazy model load |
| 변수 & 보안 비밀 | `OPENAI_API_KEY`, `JWT_SECRET`, `ADMIN_ID`, `ADMIN_PASSWORD` | all four secrets; `MODEL_*` are baked in |

Every push to the connected branch then triggers a Cloud Build + redeploy — no
local Docker or `gcloud` needed. The build takes ~10 min (torch is ~800 MB
installed); if it fails with `TIMEOUT`, raise the generated trigger's timeout in
Cloud Build. `./scripts/deploy-cloudrun.sh` (wrapping `gcloud run deploy
--source .`) remains a one-off CLI alternative — export all four secrets in your
shell first (it hard-fails if any is missing); it already passes the table's
values as flags.

The container filesystem on Cloud Run is **in-memory**, so `backend/uploads/`
and `backend/db/agrisage.db` count against the 2 GiB and vanish when the
instance scales to zero — **including every user account, crop, and diagnosis
record** (accepted demo limitation; moving to Cloud SQL/GCS is a separate,
deliberate task). The admin account is re-seeded from env at every boot, and
JWTs are stateless so surviving tokens stay *signed*-valid — the API treats a
token whose user row is gone as a stale session (401 → forced re-login).

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
  app.py           Entry point. load_dotenv() FIRST, then init_db() + admin
                    seeding at import. "/" serves frontend/landing.html;
                    "/<path>" serves any other frontend/* file. Errors are
                    always {"status":"error","message":...} (incl. a JSON 413
                    handler). API routes (all /api/* below except signup/login
                    require `Authorization: Bearer <JWT>`):
                    - POST /api/signup {email,password≥8,certification,
                      purpose} → 201 {token, profile}; dup email → 409.
                    - POST /api/login {email,password} → {token, profile};
                      one generic 401 (no user enumeration).
                    - GET/PUT /api/profile: profile = {email, role,
                      certification, purpose, daily_limit, used_today}.
                      PUT accepts only certification/purpose.
                    - GET/POST /api/crops, PUT/DELETE /api/crops/<id>:
                      per-user crops (snake_case fields); color must be hex
                      (it lands in style="background:..."), non-owned = 404.
                    - POST /api/diagnose: multipart {image (jpg/jpeg/png,
                      ≤10MB), crop_id, user_input}. Personalization is
                      SERVER-side: certification from the user row,
                      growing_environment/harvest_date from the crop row,
                      purpose = crop.purpose_override || user.purpose; the
                      response echoes effective_purpose (also stored inside
                      result_json for history re-entry). Daily-limit check
                      (KST midnight boundary) runs BEFORE the upload is
                      saved → 429; then pipeline.diagnose(), persists with
                      user_id (healthy/uncertain rows get follow_up_status
                      "not_needed"), returns result + diagnosis_id.
                    - POST /api/diagnose/<id>/ask: free-text Q&A via RAG +
                      GPT; ownership-checked (no UI yet).
                    - PUT /api/diagnose/<id>/follow-up
                      {follow_up_status: resolved|escalate}.
                    - GET /api/history: OWN diagnoses only, newest first,
                      pre-shaped for the UI (KST date, crop name/emoji/color
                      LEFT JOINed with fallbacks, disease label, raw result
                      with diagnosis_id injected).
                    - GET /api/admin/users (per-user info + used_today/
                      total_count/last_diagnosis_at), PUT
                      /api/admin/users/<id>/limit {daily_limit: 0..999|null}
                      — admin role only (403 otherwise).
  auth.py          JWT + password layer, deliberately DB-free: PyJWT HS256
                    tokens {uid,email,role,exp:+7d} signed with JWT_SECRET
                    (insecure dev fallback + one-time warning if unset),
                    pbkdf2:sha256 hashing (NOT werkzeug's scrypt default —
                    ~32MB/call next to resident torch), require_auth /
                    require_admin decorators that set g.user.
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
                    need the training dataset on disk. The lazy load is behind
                    a double-checked lock — gunicorn runs several threads, and
                    simultaneous first requests each building their own model
                    is an OOM on a 2Gi Cloud Run instance, not just waste.
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
    models.py       Schema + init_db() (called at app import): users (email
                    UNIQUE NOCASE, role, certification, purpose, daily_limit
                    — NULL = unlimited, default 3), crops (per user),
                    diagnoses (+user_id), follow_up_reminders (still
                    unwired). init_db() also migrates pre-auth DBs: PRAGMA
                    table_info → ALTER TABLE adds diagnoses.user_id, THEN
                    creates the (user_id, created_at) index (order matters —
                    the index can't go in the executescript'd _SCHEMA).
                    Legacy rows keep user_id NULL → invisible to everyone.
    crud.py         Explicit column lists everywhere (no SELECT * — a new
                    column must never silently leak into an API response).
                    Users/crops/diagnoses CRUD, upsert_admin,
                    count_diagnoses_since + kst_today_start_utc() (KST is a
                    fixed +9 offset constant — no DST since 1988, so no
                    tzdata dependency; returns UTC "YYYY-MM-DD HH:MM:SS" so
                    a lexical created_at >= compare hits the index),
                    admin_list_users, get_due_follow_ups /
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
                    opencv-python-headless. Deliberately NO training-only
                    packages (pandas, tensorboard, ...): the inference import
                    chain pipeline -> predict -> model.model -> base -> logger
                    -> utils must stay importable with just this list, which
                    is why models/utils/util.py imports pandas lazily. A
                    module-level import there makes every /api/diagnose in
                    production return the friendly 500 while dev machines
                    (conda env1 has pandas) look fine.
frontend/           Static HTML + Tailwind CSS, no JS framework.
  landing.html        Entry page ("/"). "Log in" CTA -> login.html, plus
                      "Continue as guest" -> index.html.
  login.html         REAL login: apiLogin() → stores the JWT, redirects to
                      dashboard.html; inline error banner. The email input is
                      type="text" (inputmode="email") ON PURPOSE — ADMIN_ID
                      may not be email-shaped and type="email" would block
                      admin login. Admin lands on dashboard like everyone.
  signup.html        Adds certification (conventional/organic) and default
                      purpose (self_consumption/sale) radios; apiSignup()
                      (password minlength 8) → token stored, dashboard.
  dashboard.html      Home for logged-in users: crops (await getCrops()), a
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
                      Writes NOTHING — the server recorded the diagnosis
                      during /api/diagnose, so a refresh just re-renders;
                      the follow-up CTA links the server diagnosis id (or
                      historyId when re-entered from history). PHI banner
                      prefers result.effectivePurpose over the current
                      profile.
  follow-up.html      3-checkbox post-treatment check-in for one diagnosis
                      (?id=<server id>). PUT /api/diagnose/<id>/follow-up
                      resolved/escalate.
  history.html        Past diagnoses (GET /api/history, server-shaped).
                      Re-enters diagnosis-result.html read-only; clicks find
                      the entry in the already-fetched list with a String()
                      id compare (server ids are numbers, data-attrs are
                      strings).
  mypage.html         Edit account personalization (PUT /api/profile) +
                      manage crops (PUT/DELETE /api/crops/<id>), Sign out
                      button (logout()), and — only when profile.role ===
                      "admin" — an "Admin dashboard" card linking admin.html.
                      The notifications toggle is the ONE remaining
                      localStorage-backed state.
  admin.html          Admin-only dashboard: per-user cards (email, role
                      badge, joined date, certification·purpose, Today X/Y
                      with ∞ for null, total, last diagnosis) and an inline
                      daily-limit editor (0 blocks, empty/Unlimited = null)
                      via adminListUsers()/adminSetLimit(). Client guard
                      bounces non-admins to dashboard; the API enforces 403
                      regardless.
  index.html          Guest-only simple home. Its header links point at
                      logged-in pages, whose requireAuth() bounces guests to
                      login.html — that IS the guest diagnosis block.
  js/store.js          The fetch layer (function names kept from the old
                      localStorage mock, but data functions are now ASYNC —
                      pages await them in an init IIFE). Token helpers
                      (localStorage "agrisage_token", getToken/setToken/
                      clearToken), requireAuth() page guard, logout(),
                      authFetch() (Bearer header; on 401 clears the token
                      and redirects to login.html), apiSignup/apiLogin,
                      getProfile/saveProfile, getCrops/addCrop/updateCrop/
                      removeCrop, getHistory/findHistoryEntry/updateFollowUp,
                      adminListUsers/adminSetLimit, resolvePurpose (labels/
                      legacy fallback only — the server owns the real chain),
                      escapeHtml(), diagnoseWithApi({imageBlob, cropId,
                      userInput}) (FormData with a normalized ASCII filename —
                      the backend's secure_filename strips non-ASCII names)
                      and mapDiagnosisResponse() (API → render shape, incl.
                      effectivePurpose). On load it deletes the legacy
                      agrisage_profile/crops/history localStorage keys.
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
                    at the committed weights/config6) plus OMP/MKL_NUM_THREADS=2,
                    and runs gunicorn (1 worker, 4 threads) bound to $PORT.
                    OPENAI_API_KEY / JWT_SECRET / ADMIN_ID / ADMIN_PASSWORD
                    are supplied at deploy time.
.dockerignore       Keeps the build context small (excludes .venv,
                    node_modules, generated CSS, uploads, the SQLite db, .env,
                    and the training-only models/dataset + models/saved) — but
                    NOT the committed model weights.
scripts/
  deploy-cloudrun.sh  Wraps `gcloud run deploy --source .` (Cloud Build builds
                    the Dockerfile — no local Docker). Requires
                    OPENAI_API_KEY/JWT_SECRET/ADMIN_ID/ADMIN_PASSWORD in the
                    shell (hard-fails otherwise); SERVICE/REGION overridable
                    via env (default asia-northeast3). Passes the same
                    memory/CPU/concurrency/timeout values as the console
                    table in "Commands".
```

**Path convention**: `backend/app.py` resolves `frontend/` relative to its own
file location (`BASE_DIR/frontend`), not the process CWD, and
`backend/ai/pipeline.py` resolves relative `MODEL_*` env paths against the
repo root — the app works whether started from the repo root, from inside
`backend/`, or via `gunicorn --chdir backend`.

**Screen flow**: `landing.html` (entry, "/") -> `login.html` / `signup.html`
(real JWT auth) -> `dashboard.html` (home) -> `crop-select.html` (register a
crop) -> `diagnose.html` (camera or gallery photo for a specific crop) ->
`diagnosis-result.html` (traffic light + analyzed photo w/ leaf bbox + GPT
explanation + treatment) -> `follow-up.html` (post-treatment check-in).
`history.html` lists past diagnoses and re-enters `diagnosis-result.html` in
read-only mode. `mypage.html` edits the account and crop list, holds Sign out,
and (admin only) links `admin.html`. `index.html` is a separate guest-only
home reachable via landing's "Continue as guest". Every logged-in page calls
`requireAuth()` as the first line of its inline script (token presence →
otherwise redirect to login.html) and runs its init inside an async IIFE
because the store.js data functions are async. Pages link with plain
`<a href>` / `window.location.href` and pass state via URL query params
(`crop`, `color`, `emoji`, `cropId`, history `id` — server ids are NUMBERS,
so compare with `String(a) === String(b)`) or, for the diagnosis payload
(image data URL + mapped result), via
`sessionStorage["agrisage_pending_diagnosis"]`. There is no client-side
router.

**Navigation**: the logged-in pages (`dashboard`, `crop-select`, `diagnose`,
`diagnosis-result`, `follow-up`, `history`, `mypage`, `admin`) all share the
same top `<header>` — logo row plus Home/Diagnose/History/Profile tabs
(`sticky top-0`), Home -> `dashboard.html`. Except on `dashboard.html`
there's also a back-arrow + page-title row inside the same `<header>`. When
adding a page to the logged-in flow, copy the shared header block; don't
reintroduce a bottom nav.

**Personalization & the confidence gate**: the three personalization
variables are `certification` (account-level), `growing_environment`
(per-crop), and `purpose` (account default, per-crop override). The
**effective purpose is resolved server-side** in `/api/diagnose`
(`crop.purpose_override || user.purpose`), echoed as `effective_purpose`,
and stored inside `result_json` so history re-entries show the purpose used
at diagnosis time — the client `resolvePurpose(crop, profile)` copy exists
only for list labels and as a fallback for pre-auth stored results; keep the
two chains identical. The **confidence gate is enforced server-side** in
`pipeline.py`: `confidence < 70` returns status "uncertain" BEFORE the
healthy check (a low-confidence "healthy" must not reassure the user);
severity "very high" makes traffic_light "urgent". `diagnosis-result.html`
trusts `result.status` when present and only applies the legacy client-side
`confidence < 70` gate to old/mock results that lack one. Don't reorder
either gate.

**Auth & usage limits**: JWT (PyJWT HS256, 7-day expiry, payload
{uid, email, role}) in `localStorage["agrisage_token"]`, sent as
`Authorization: Bearer`. Passwords are pbkdf2:sha256 hashes in the users
table. The admin account is whatever `ADMIN_ID`/`ADMIN_PASSWORD` say at boot
(re-upserted every start; role='admin', daily_limit NULL). Every user gets
`daily_limit` (default **3**) diagnoses per **KST calendar day**, enforced in
`/api/diagnose` BEFORE the upload is saved (429; count-then-insert isn't
atomic across gunicorn threads — worst case one extra, accepted).
Admins adjust per-user limits from `admin.html` (0 blocks, null = unlimited).
Guests can browse `index.html` but every data page/API requires a token —
that's the guest-diagnosis block. A token whose user row vanished (Cloud Run
DB reset) gets 401 → authFetch clears it and returns to login.

**Frontend/backend boundary** — current reality: **nothing is mocked
anymore.** Auth, profile, crops, diagnosis, history, follow-up state, and
the admin panel are all real API calls through `store.js` (async — pages
await them). The only client-side state left: the mypage notifications
toggle (`localStorage["agrisage_notifications_enabled"]`, nothing consumes
it yet) and the transient `sessionStorage` diagnosis payload. When adding a
new endpoint, follow the `store.js` pattern: an async function that
`authFetch`es, maps snake_case → camelCase, and throws `Error(message)` from
the server's `{"status":"error","message":...}` body.

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
