# AgriSage

> Agriculture + Sage. "We don't just name the problem. We walk you through it."

AgriSage is an AI-powered agricultural support service that diagnoses crop diseases from a
single photo, explains the diagnosis in plain language, recommends a treatment tailored to
the grower's actual situation, and follows up after treatment to confirm the crop is
recovering.

## The Problem

New and returning farmers often can't tell what's wrong with their crop — and even when a
diagnosis is available, they don't know which treatment is safe and appropriate for their
specific situation. Existing diagnostic apps stop at naming the disease; none of them explain
the reasoning, personalize the recommendation, check safety standards, or follow up after
treatment.

## What AgriSage Does

1. **Diagnose** — A CNN-based image classification model identifies the crop disease from a
   single photo across 38 crop-disease classes spanning 14 crops.
2. **Explain** — An LLM (Gemini) translates the confirmed diagnosis into an easy-to-understand
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
│   ├── app.py              # App entry point, static serving + /api/diagnose
│   ├── requirements.txt
│   └── models/             # Diagnostic model code/weights (to be integrated)
├── frontend/               # Static screens (Mobile-first), styled with Tailwind CSS
│   ├── landing.html        # Start screen ("/"), service introduction + "Log in" button
│   ├── login.html          # Login form (submits to dashboard.html)
│   ├── signup.html         # Signup + certification (conventional/organic) & purpose (self-consumption/sale)
│   ├── dashboard.html      # Home after login: registered crops, diagnosis CTA, follow-up banner
│   ├── crop-select.html    # Crop registration: 14 crops + environment/purpose/expected harvest date
│   ├── diagnose.html       # Photo upload (includes camera tips) → redirects to diagnosis-result.html
│   ├── diagnosis-result.html # Diagnosis result: status lights (🟢🟡🔴), cause/description, tailored recommendation, PHI banner
│   ├── follow-up.html      # Post-treatment follow-up checklist (3 questions) → branches results
│   ├── history.html        # Past diagnosis history list → reuses result page in history mode
│   ├── mypage.html         # Profile edit, crop management (edit/delete), notification settings
│   ├── index.html          # (Guest only) Home: diagnosis start CTA, 4-step flow, differentiator cards
│   ├── js/store.js         # localStorage-based mock profile/crop/history + mock AI diagnosis
│   ├── js/pwa.js           # Service worker registration (included in all pages)
│   ├── sw.js                # Service worker: offline caching (pre-caches all pages)
│   ├── manifest.webmanifest # PWA manifest (app name/icons/theme color)
│   ├── icons/               # PWA icons (192/512/maskable/apple-touch/favicon)
│   ├── src/input.css       # Tailwind entry point (@tailwind + custom component classes)
│   ├── css/styles.css      # Build output (not committed, generated via npm run build)
│   ├── tailwind.config.js  # Tailwind theme settings (custom color palette, etc.)
│   └── package.json
├── render.yaml             # Render deployment configuration
├── scripts/                # Local environment setup scripts
│   ├── setup.sh            # macOS / Linux
│   └── setup.ps1           # Windows (PowerShell)
└── README.md
```

## User Flow

```
Start Screen → Login/Signup → Dashboard → Register Crop → Upload Photo
  → Diagnosis Result (Status Light + Explanation + Recommendation) → Follow-up Checklist → (Re-view in History)
```

Users can try out the existing `index.html` (simple home) flow without logging in by selecting "Continue as guest" on the `landing.html` screen. After logging in/signing up, `dashboard.html` serves as the home screen, displaying registered crops and post-treatment follow-up alerts.

Logged-in screens (Dashboard, Crop Registration, Diagnosis, Result, Follow-up, History, Profile) share a common header (Logo + Home, Diagnose, History, Profile tabs) applied across all pages for a consistent navigation experience.

### Personalization Variables and Status Light Logic

- `certification` (conventional/organic): Account-level variable, collected during signup.
- `growing_environment` (open field/greenhouse), `purpose` (self-consumption/sale): Crop-level variables, collected during crop registration (`purpose` can override the default account setting per crop).
- **Status Lights**:
  - If the diagnosis confidence is below 70%, the disease is not confirmed. The status becomes yellow (🟡), recommending expert consultation.
  - If the severity is "very high", the status is marked red (🔴) regardless of confidence.
- Crops grown for "sale" will display an emphasized PHI (Pre-Harvest Interval) safety banner on the diagnosis result page.

### Mock Data

Since the backend does not yet integrate actual models or databases, `frontend/js/store.js` mocks profiles, crops, and diagnostic history using `localStorage`, and `mockDiagnose()` returns simulated diagnostic results. Once the actual API is ready, these mock functions can be replaced with `fetch()` calls (refer to `CLAUDE.md` for endpoint candidates).

## Hybrid (Web + App)

AgriSage is configured as a Progressive Web App (PWA), serving both the web version and the installable app from the same codebase.

- **PWA Settings**: All HTML pages link to `manifest.webmanifest`, app icons, and iOS `apple-mobile-web-app-*` meta tags in their `<head>`, and load `js/pwa.js` to register the service worker (`sw.js`).
- **Web App**: When accessed via a browser URL, it functions as a regular website.
- **Installable App**: Users can install AgriSage via Chrome/Edge/Android address bar install icons, or using Safari's "Add to Home Screen" sharing option. Once installed, it runs in a standalone window without the browser address bar, with its own home screen icon.
- **Offline Capability**: `sw.js` pre-caches all HTML pages, `css/styles.css`, and `js/store.js`, so previously visited screens will open even offline or under unstable network conditions. HTML pages use a network-first strategy (always fetch the latest online), while other static assets use a cache-first strategy.
- **Cache Versioning**: If you modify pre-cached file lists or content, make sure to bump the `CACHE_NAME` version in `frontend/sw.js` (e.g., `agrisage-v1` → `agrisage-v2`) to trigger cache updates on client devices.
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

```bash
python backend/app.py          # http://localhost:5000
```

Or run it with Gunicorn (production environment equivalent):

```bash
gunicorn --chdir backend app:app
```

## Frontend Styles (Tailwind CSS)

The `frontend/` directory uses Node/npm and the Tailwind CLI for styles. While setup scripts handle this automatically, if you want to work on frontend files independently:

```bash
cd frontend
npm install
npm run build     # Generates css/styles.css once
npm run watch     # Auto-rebuilds on file changes (keep running during development)
```

- Each HTML file uses Tailwind utility classes. There is minimal custom CSS. State-based classes toggled by JS via `classList` (such as `.crop-card.selected`, `.next-btn.ready`, and `.spinner.show`) are defined in `frontend/src/input.css` using `@layer components` and `@apply`.
- The color palette (`page`, `app`, `ink`, `muted`, `accent`, `accent-dark`, `accent-soft`, `card`, `border`, `warn`) is configured in `frontend/tailwind.config.js`. Avoid using inline hex colors; add them to the Tailwind configuration instead.
- `frontend/css/styles.css` is a build artifact and is not committed to git (per `.gitignore`). You must build it locally to view the styled pages.

## Notes

- These pages serve as a prototype/demo. Integration with actual image classification models, disease-treatment mapping DBs, or PLS data is not implemented in this mockup.
- For PRD and technical requirements, please refer to the team documentation.
