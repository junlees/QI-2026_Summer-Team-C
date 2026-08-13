# AgriSage

> Agriculture + Sage. "We don't just name the problem. We walk you through it."

## Team Introduction

**Team C** — QI 2026 Summer

| Name | Role |
|------|------|
| Hyunjun Lee | Team leader · AI model |
| Hanmin Bae | Backend |
| Minseong Hong | Dataset |
| Najin Son | Dataset |
| Sehyeon Kim | Frontend · LLM |

## Service Introduction

AgriSage is an AI-powered agricultural support service that diagnoses crop diseases from a
single photo, explains the diagnosis in plain language, recommends a treatment tailored to
the grower's actual situation, and follows up after treatment to confirm the crop is
recovering.

Take (or upload) a photo of a leaf and AgriSage detects the leaf in the frame, classifies
the disease with a fine-tuned GoogLeNet model, grounds the result in a structured disease
knowledge base, and has an LLM (OpenAI GPT) walk you through the diagnosis — what it is,
why it happened, and what to do — adjusted to your certification (conventional/organic),
growing environment, harvest schedule (PHI safety), and level of experience. Delivered as
an installable PWA that works on both web and mobile.

## The Problem

New and returning farmers often can't tell what's wrong with their crop — and even when a
diagnosis is available, they don't know which treatment is safe and appropriate for their
specific situation. Existing diagnostic apps stop at naming the disease; none of them explain
the reasoning, personalize the recommendation, check safety standards, or follow up after
treatment.

## What AgriSage Does

1. **Diagnose** — A CNN-based image classification model identifies the crop disease from a
   single photo. The deployed checkpoint is a 12-class GoogLeNet covering Apple, Grape, and
   Tomato; the disease knowledge base behind it spans 38 classes across 14 crops, so the
   model's coverage can be widened without touching the rest of the pipeline.
2. **Explain** — An LLM (OpenAI GPT) translates the confirmed diagnosis into an easy-to-understand
   explanation of the symptoms and cause — without re-diagnosing or inventing facts.
3. **Personalize** — A rule-based filter narrows treatment options based on the grower's
   certification status (conventional/organic), growing environment (open field/greenhouse),
   and purpose (self-consumption/sale), and explains why other options were excluded.
4. **Check Safety** — Recommended products are checked against pre-harvest interval (PHI)
   standards so growers don't risk pesticide residue violations before harvest.
5. **Follow Up** — After treatment, a simple checklist confirms whether the crop is
   recovering, and routes growers to expert consultation if it isn't.

## Key Differentiators

Unlike existing diagnostic services, AgriSage doesn't stop at a diagnosis:

| Capability | Government App | Farmdy | KyungNong AI | AgriSage |
|---|:---:|:---:|:---:|:---:|
| Explainable diagnosis | ✗ | △ | ○ | ✓ |
| Personalized treatment recommendation | ✗ | ✗ | ○ | ✓ |
| Built-in safety check (PHI) | ✗ | ✗ | △ | ✓ |
| Post-treatment follow-up | ✗ | △ | ✗ | ✓ |

## How It Works

```
Photo upload → CNN diagnosis (class + confidence) → RAG knowledge base lookup
→ Rule-based personalization filter → LLM-generated explanation → Result + recommendation
```

The LLM never diagnoses — it only explains and curates facts already confirmed by the CNN
model and a structured knowledge base, grounded to prevent hallucination.

## Project Structure

```
.
├── backend/                # Flask server (deployment + model integration)
│   ├── app.py              # App entry point: static serving + auth/profile/crops/diagnose/history/admin API
│   ├── auth.py             # JWT issue/verify + password hashing + require_auth/require_admin
│   ├── ai/                 # Diagnosis pipeline: leaf detection → CNN → RAG lookup → LLM explanation
│   ├── db/                 # SQLAlchemy/Alembic persistence (PostgreSQL prod, SQLite local)
│   ├── tests/              # Auth, migration, admin-race, and model-unavailable suites
│   ├── requirements.txt
│   └── models/             # Diagnostic model code/weights (incl. leaf_detect.py)
├── frontend/               # Static screens (Mobile-first), styled with Tailwind CSS
│   ├── landing.html        # Start screen ("/"), service introduction + "Log in" button
│   ├── login.html          # Real login (POST /api/login → JWT); admin logs in here too
│   ├── signup.html         # Signup (POST /api/signup) + certification (conventional/organic) & purpose (self-consumption/sale)
│   ├── dashboard.html      # Home after login: registered crops, diagnosis CTA, follow-up banner
│   ├── crop-select.html    # Crop registration: Apple/Grape/Tomato (the deployed model's coverage) + environment/purpose/expected harvest date
│   ├── diagnose.html       # In-page camera capture or gallery upload (JPEG/PNG) → redirects to diagnosis-result.html
│   ├── diagnosis-result.html # Diagnosis result: status lights (🟢🟡🔴), analyzed photo with the detected leaf box, cause/description, tailored recommendation, PHI banner
│   ├── follow-up.html      # Post-treatment follow-up checklist (3 questions) → branches results
│   ├── history.html        # Past diagnosis history list → reuses result page in history mode
│   ├── mypage.html         # Profile edit, crop management (edit/delete), sign out, admin-page link (admins)
│   ├── admin.html          # Admin dashboard: per-user info/usage + daily-limit editor
│   ├── index.html          # (Guest only) Home: diagnosis start CTA, 4-step flow, differentiator cards
│   ├── js/store.js         # API layer: JWT helpers + fetch-backed profile/crops/history/diagnosis
│   ├── js/pwa.js           # Service worker registration (included in all pages)
│   ├── sw.js                # Service worker: offline caching (pre-caches all pages)
│   ├── manifest.webmanifest # PWA manifest (app name/icons/theme color)
│   ├── icons/               # PWA icons (192/512/maskable/apple-touch/favicon)
│   ├── src/input.css       # Tailwind entry point (@tailwind + custom component classes)
│   ├── css/styles.css      # Build output (not committed, generated via npm run build)
│   ├── tailwind.config.js  # Tailwind theme settings (custom color palette, etc.)
│   └── package.json
├── Dockerfile              # Cloud Run container (Tailwind build + Python runtime)
├── .dockerignore           # Build-context excludes (keeps the model weights)
├── .github/workflows/      # CI: static checks, tests, production import check
├── scripts/                # Setup + deploy scripts
│   ├── setup.sh            # macOS / Linux
│   ├── setup.ps1           # Windows (PowerShell)
│   ├── demo.sh             # Dev server + public Cloudflare tunnel (start/stop/status/url/logs)
│   └── deploy-cloudrun.sh  # Deploy to Google Cloud Run
└── README.md
```

## User Flow

```
Start Screen → Login/Signup → Dashboard → Register Crop → Upload Photo
  → Diagnosis Result (Status Light + Explanation + Recommendation) → Follow-up Checklist → (Re-view in History)
```

Guests can browse `index.html` (simple home) via "Continue as guest" on the `landing.html` screen, but every data screen and API requires an account — diagnosis itself is login-only (the per-user daily limit needs an identity). After logging in/signing up, `dashboard.html` serves as the home screen, displaying registered crops and post-treatment follow-up alerts.

Logged-in screens (Dashboard, Crop Registration, Diagnosis, Result, Follow-up, History, Profile) share a common header (Logo + Home, Diagnose, History, Profile tabs) applied across all pages for a consistent navigation experience.

### Personalization Variables and Status Light Logic

- `certification` (conventional/organic): Account-level variable, collected during signup.
- `growing_environment` (open field/greenhouse), `purpose` (self-consumption/sale): Crop-level variables, collected during crop registration (`purpose` can override the default account setting per crop).
- **Status Lights**:
  - If the diagnosis confidence is below 70%, the disease is not confirmed. The status becomes yellow (🟡), recommending expert consultation.
  - If the severity is "very high", the status is marked red (🔴) regardless of confidence.
- Crops grown for "sale" will display an emphasized PHI (Pre-Harvest Interval) safety banner on the diagnosis result page.

### Accounts, Auth & Daily Limits

Signup/login are real: the server stores accounts with pbkdf2-hashed passwords and issues a **JWT (7-day expiry)** that `frontend/js/store.js` sends as `Authorization: Bearer`. JWTs carry an immutable UUID subject and token version; every protected request reloads the current user/role from the database. Profiles, crops, and diagnosis history all live server-side, scoped per user.

Each user may run **3 diagnoses per day** by default (KST midnight reset). An
**admin account** — credentials from `ADMIN_ID` / `ADMIN_PASSWORD`, guarded by
the monotonic `ADMIN_CONFIG_VERSION` — sees an "Admin dashboard" button in the
profile page (`admin.html`), listing every user's info and usage and allowing
per-user daily-limit changes (0 blocks a user; unlimited removes the cap).
Increment `ADMIN_CONFIG_VERSION` whenever either credential changes. This makes
older Cloud Run revisions no-op instead of allowing them to restore an old
password; rotating `ADMIN_ID` also demotes the previous admin and revokes its
tokens.

The demo Cloud Run image uses an explicitly enabled SQLite database under
`/tmp`. Accounts, sessions, crops, and diagnosis history reset whenever the
instance is replaced, restarted, or scaled to zero. Set
`ALLOW_EPHEMERAL_SQLITE=false` and provide a PostgreSQL `DATABASE_URL` for a
persistent deployment.

## Hybrid (Web + App)

AgriSage is configured as a Progressive Web App (PWA), serving both the web version and the installable app from the same codebase.

- **PWA Settings**: All HTML pages link to `manifest.webmanifest`, app icons, and iOS `apple-mobile-web-app-*` meta tags in their `<head>`, and load `js/pwa.js` to register the service worker (`sw.js`).
- **Web App**: When accessed via a browser URL, it functions as a regular website.
- **Installable App**: Users can install AgriSage via Chrome/Edge/Android address bar install icons, or using Safari's "Add to Home Screen" sharing option. Once installed, it runs in a standalone window without the browser address bar, with its own home screen icon.
- **Offline Capability**: `sw.js` pre-caches all HTML pages, `css/styles.css`, and `js/store.js`, so previously visited screens will open even offline or under unstable network conditions. HTML, CSS, and JS are all **network-first** — the cache is a fallback only when the network fails. This is deliberate: serving a cached `styles.css` after a Tailwind rebuild produced confusing stale-style bugs during development. Only the icons and the manifest, which rarely change, are cache-first.
- **Cache Versioning**: If you add, rename, or remove a pre-cached file, update `PRECACHE_URLS` **and** bump `CACHE_NAME` in `frontend/sw.js` (currently `agrisage-v5`) so client devices discard the old cache.
- **HTTPS/Localhost**: Service workers only register in secure contexts (HTTPS or `localhost`). Local development (`http://localhost:5000`) works out of the box.

## First Setup (Cloning the Repository)

Requires Python 3.11 (refer to `backend/.python-version`).

**macOS / Linux**
```bash
./scripts/setup.sh
source .venv/bin/activate
```

**Windows (PowerShell)**
```powershell
./scripts/setup.ps1
.\.venv\Scripts\Activate.ps1
```

Alternatively, you can install the dependencies directly without a virtual environment:
```bash
pip install -r backend/requirements.txt
```

## Running the Application

Create a `.env` at the repo root (`load_dotenv()` runs before anything reads the
environment, and python-dotenv also searches parent directories):

```bash
# Required — the server refuses to start without a JWT_SECRET of 32+ bytes.
# Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET=<64 hex characters>
OPENAI_API_KEY=<your key>

# Required for real diagnoses. Relative paths resolve against the repo root,
# so these work from any working directory. Without them, /api/diagnose
# returns HTTP 503 model_unavailable — it never fabricates a result.
MODEL_CHECKPOINT_PATH=backend/models/weights/classification_model.pth
MODEL_CONFIG_PATH=backend/models/config6.json

# Optional managed admin — set all three together or omit all three.
ADMIN_ID=<admin login id>
ADMIN_PASSWORD=<long random password>
ADMIN_CONFIG_VERSION=1

# Optional overrides: OPENAI_MODEL (default gpt-4o-mini),
# OPENAI_EMBEDDING_MODEL (default text-embedding-3-small)
```

Then start the server:

```bash
python backend/app.py          # http://localhost:5000
```

When `DATABASE_URL` is omitted locally, the app uses
`backend/db/agrisage.db`. Cloud Run never permits that fallback.

Or run it with Gunicorn (production environment equivalent):

```bash
gunicorn --chdir backend app:app
```

### Quick public demo (no Cloud Run)

Camera capture needs a secure context, so `http://<your-LAN-ip>:5000` will not
work from a phone. `scripts/demo.sh` runs the dev server behind a Cloudflare
quick tunnel and prints a temporary public HTTPS URL:

```bash
./scripts/demo.sh start     # server + public HTTPS URL
./scripts/demo.sh url       # print the URL again
./scripts/demo.sh stop      # shut both down
```

The hostname is random and changes on every start, so re-share it after each
restart.

### Deploy to Google Cloud Run

Production runs as a container built from the repo-root `Dockerfile`.

**Continuous deployment from GitHub (recommended).** In the Cloud Run console,
create the service with **"Continuously deploy from a repository (source or
function)"**, connect this GitHub repo and the branch you deploy from, and set
**Build Type: Dockerfile** (source location `/Dockerfile`, repo root).

Then change these — the defaults will not run this service:

| Console field | Value | Why |
|---|---|---|
| Authentication | **Allow public access** | otherwise every request is 403 |
| Memory | **2 GiB** | the 512 MiB default OOM-kills torch on the first diagnosis |
| CPU | 2 | matches the `OMP_NUM_THREADS=2` baked into the image |
| Max concurrent requests | 4–8 | the default 80 just queues behind one gunicorn worker |
| Request timeout | 300s | the first request also pays the lazy model load |
| Maximum instances | **1** | ephemeral SQLite cannot be shared across instances |
| Cloud SQL | **no connection** | the disposable demo does not use Cloud SQL |
| Service account | dedicated runtime identity | needs scoped Secret Accessor access |
| Secret Manager | `OPENAI_API_KEY`, `JWT_SECRET`, `ADMIN_ID`, `ADMIN_PASSWORD` | use pinned numeric secret versions |
| Environment variable | `ADMIN_CONFIG_VERSION=1` | increment for every admin ID/password rotation |

Memory/CPU/concurrency live under **Containers → Settings** on the create form
and can be edited later via "Edit & deploy new revision". Every push to the
connected branch then triggers a Cloud Build + redeploy — no local Docker or
`gcloud` needed. The build takes roughly 10 minutes (torch is ~800 MB
installed); if it ever fails with `TIMEOUT`, raise the timeout on the trigger
Cloud Run generated in Cloud Build.

Uploaded photos and detector crops under `backend/uploads/` are deleted in a
`finally` block after each inference attempt. The demo database lives at
`/tmp/agrisage-demo.db`; all users and history disappear with the Cloud Run
instance. Existing JWTs also become invalid because their user UUID no longer
exists in the new database.

**One-off deploy from the CLI (alternative).** With the `gcloud` CLI
authenticated and a project selected:

```bash
export RUN_SERVICE_ACCOUNT=agrisage-run@PROJECT_ID.iam.gserviceaccount.com
export OPENAI_API_KEY_SECRET_REF=agrisage-openai-api-key:1
export JWT_SECRET_SECRET_REF=agrisage-jwt-secret:1
export ADMIN_ID_SECRET_REF=agrisage-admin-id:1
export ADMIN_PASSWORD_SECRET_REF=agrisage-admin-password:1
export ADMIN_CONFIG_VERSION=1
export EPHEMERAL_DEMO=true
./scripts/deploy-cloudrun.sh
```

The script uses `gcloud run deploy --source .`, so Cloud Build builds the
Dockerfile — no local Docker needed. `MODEL_CHECKPOINT_PATH` / `MODEL_CONFIG_PATH`
are baked into the image; Cloud Run injects `$PORT` and gunicorn binds to it.
Demo mode enforces `MAX_INSTANCES=1`.

For persistent production, set `EPHEMERAL_DEMO=false`, provide
`CLOUD_SQL_INSTANCE` and a version-pinned `DATABASE_URL_SECRET_REF`, and grant
the runtime identity Cloud SQL Client access. The first rollout should point at
an empty PostgreSQL database. Alembic runs under a PostgreSQL advisory lock and
the configured database user currently needs schema DDL plus runtime CRUD
rights.

## Tests

Run the local security, migration, auth, and model-unavailable suite with:

```bash
python -m unittest discover -s backend/tests -v
ruff format --check backend/app.py backend/auth.py backend/ai/pipeline.py backend/db backend/tests
ruff check backend/app.py backend/auth.py backend/ai/pipeline.py backend/db backend/tests
```

The suite is 27 tests and needs no environment setup — each test supplies its
own configuration. Four of them are PostgreSQL integration tests and skip
themselves unless `TEST_POSTGRES_DATABASE_URL` points to a dedicated empty
database whose name ends in `_test`; they cover migrations, concurrent admin
rotations, signup/admin conflicts, foreign key actions, and restart safety.

`.github/workflows/p0-security.yml` runs on every push and pull request:

| Step | What it checks |
|---|---|
| Static checks | `ruff format --check`, `ruff check`, and `bash -n` on the shell scripts |
| Unit tests | the 23 tests that cover the deployed configuration (the 4 PostgreSQL tests skip) |
| Production server import check | `gunicorn --check-config` against `app:app` in Cloud Run demo mode, so an import that only works on a dev machine fails here instead of in production |

While the deployment runs on disposable SQLite, CI does **not** start a
PostgreSQL service container — the integration tests skip themselves and there
is nothing for it to serve. To re-enable them, restore the `postgres:16`
service block and `TEST_POSTGRES_DATABASE_URL` in the workflow (a comment there
marks the spot).

`ruff` is pinned in the workflow. It is a linter whose default rule set widens
between releases, so an unpinned install silently turns unrelated style
findings into a red build; every other tool in that install list is pinned for
the same reason.

## Frontend Styles (Tailwind CSS)

The `frontend/` directory uses Node/npm and the Tailwind CLI for styles. While setup scripts handle this automatically, if you want to work on frontend files independently:

```bash
cd frontend
npm install
npm run build     # Generates css/styles.css once
npm run watch     # Auto-rebuilds on file changes (keep running during development)
```

- Each HTML file uses Tailwind utility classes. There is minimal custom CSS. State-based classes toggled by JS via `classList` (such as `.crop-card.selected`, `.next-btn.ready`, and `.spinner.show`) are defined in `frontend/src/input.css` using `@layer components` and `@apply`.
- The color palette (`page`, `app`, `ink`, `muted`, `accent`, `accent-dark`, `accent-soft`, `card`, `border`, `warn`, plus the status-light colors `caution`/`caution-soft` (🟡) and `danger`/`danger-soft` (🔴)) is configured in `frontend/tailwind.config.js`. Avoid using inline hex colors; add them to the Tailwind configuration instead.
- `frontend/css/styles.css` is a build artifact and is not committed to git (per `.gitignore`). You must build it locally to view the styled pages.

## Notes

- The demo Cloud Run image and local development use SQLite. The Cloud Run demo
  database is disposable and therefore requires a one-instance maximum.
- Persistent production remains available by disabling
  `ALLOW_EPHEMERAL_SQLITE` and providing PostgreSQL `DATABASE_URL`.
- The default PostgreSQL pool is at most three connections per Cloud Run
  instance (30 at the deployment script's ten-instance cap); verify that
  budget against the selected Cloud SQL tier.
- For PRD and technical requirements, please refer to the team documentation.
