// Shared mock "backend" for the prototype: localStorage-backed profile/crops/
// history, plus a fake AI diagnosis call. Replace with real fetch() calls to
// the endpoints listed in CLAUDE.md once the backend implements them.

const STORE_KEYS = {
  profile: "agrisage_profile",
  crops: "agrisage_crops",
  history: "agrisage_history",
};

// Escape untrusted strings (URL params, API fields) before innerHTML insertion.
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function getProfile() {
  return JSON.parse(localStorage.getItem(STORE_KEYS.profile) || "null");
}
function saveProfile(profile) {
  localStorage.setItem(STORE_KEYS.profile, JSON.stringify(profile));
}

function getCrops() {
  return JSON.parse(localStorage.getItem(STORE_KEYS.crops) || "[]");
}
function saveCrops(crops) {
  localStorage.setItem(STORE_KEYS.crops, JSON.stringify(crops));
}
function addCrop(crop) {
  const crops = getCrops();
  crops.push(crop);
  saveCrops(crops);
  return crop;
}
function removeCrop(id) {
  saveCrops(getCrops().filter((c) => c.id !== id));
}

// A crop can override the account-level purpose (e.g. an organic grower
// selling most crops but keeping one for home use).
function resolvePurpose(crop, profile) {
  return (crop && crop.purposeOverride) || (profile && profile.purpose) || "self_consumption";
}

const SEED_HISTORY = [
  { id: "h1", date: "2026-07-10", cropName: "Tomato", emoji: "🍅", color: "#e63946", disease: "Early Blight", confidence: 88 },
  { id: "h2", date: "2026-06-28", cropName: "Apple", emoji: "🍎", color: "#d62828", disease: "Apple Scab", confidence: 74 },
];

function getHistory() {
  const stored = JSON.parse(localStorage.getItem(STORE_KEYS.history) || "null");
  return stored || SEED_HISTORY;
}
function addHistoryEntry(entry) {
  const history = getHistory();
  history.unshift(entry);
  localStorage.setItem(STORE_KEYS.history, JSON.stringify(history));
}
function findHistoryEntry(id) {
  return getHistory().find((h) => h.id === id) || null;
}
function updateHistoryEntry(id, patch) {
  const history = getHistory().map((h) => (h.id === id ? { ...h, ...patch } : h));
  localStorage.setItem(STORE_KEYS.history, JSON.stringify(history));
}

// Real AI diagnosis via POST /api/diagnose (leaf detection -> classifier ->
// knowledge base -> LLM explanation on the server). Maps the API response to
// the same result shape mockDiagnose() returns, plus a few extra fields
// (status, trafficLight, actions, diagnosisId), so page code stays the same.
async function diagnoseWithApi({ imageBlob, crop, profile, userInput }) {
  const form = new FormData();
  // Always send a normalized ASCII filename — the backend's secure_filename()
  // strips non-ASCII names (e.g. Korean gallery filenames) down to nothing,
  // which would fail its extension check.
  const ext = imageBlob && imageBlob.type === "image/png" ? "png" : "jpg";
  form.append("image", imageBlob, `photo.${ext}`);
  if (crop && crop.id) form.append("crop_id", crop.id);
  if (userInput) form.append("user_input", userInput);
  if (crop && crop.harvestDate) form.append("harvest_date", crop.harvestDate);
  if (profile && profile.certification) form.append("certification", profile.certification);
  if (crop && crop.growingEnvironment) form.append("growing_environment", crop.growingEnvironment);
  form.append("purpose", resolvePurpose(crop, profile));

  const res = await fetch("/api/diagnose", { method: "POST", body: form });
  if (!res.ok) {
    let message = `Diagnosis request failed (HTTP ${res.status}).`;
    try {
      const body = await res.json();
      if (body.message) message = body.message;
    } catch (e) { /* non-JSON error body */ }
    throw new Error(message);
  }
  return mapDiagnosisResponse(await res.json());
}

function mapDiagnosisResponse(api) {
  const base = {
    status: api.status,
    classId: api.class_id,
    confidence: Math.round(api.confidence),
    cropName: api.crop,
    diagnosisId: api.diagnosis_id || null,
    leafDetection: api.leaf_detection || null,
  };

  if (api.status === "healthy" || api.status === "uncertain") {
    return {
      ...base,
      name: api.status === "healthy" ? "Healthy — no disease detected" : null,
      severity: api.status === "healthy" ? "none" : "unknown",
      symptoms: api.message || null,
      cause: null,
      actions: [],
      recommendations: [],
      excluded: [],
    };
  }

  // status === "diagnosed"
  const pr = api.product_recommendation;
  const recommendations = [];
  if (pr && pr.product_name) {
    const reasonBits = [];
    if (pr.active_ingredient) reasonBits.push(`Active ingredient: ${pr.active_ingredient}.`);
    if (pr.organic_compatible_hint) reasonBits.push("Flagged as likely compatible with organic certification.");
    if (pr.safe_usage_period_days) reasonBits.push(`Pre-harvest interval: about ${pr.safe_usage_period_days} days.`);
    recommendations.push({
      product: pr.product_name,
      reason: reasonBits.join(" ") || "Matched to this diagnosis from the treatment knowledge base.",
      usage: pr.pls_check_text || "Confirm the registered product and label directions via PSIS before use.",
    });
  }

  return {
    ...base,
    trafficLight: api.traffic_light,
    name: api.disease,
    severity: api.severity,
    symptoms: [api.diagnosis_summary, api.disease_characteristics].filter(Boolean).join(" "),
    cause: api.cause,
    actions: api.recommended_actions || [],
    recommendations,
    excluded: [],
    understandingLevel: api.understanding_level || null,
  };
}

// Mock AI diagnosis (kept for offline/dev reference — the live flow now uses
// diagnoseWithApi above): picks one of a few canned outcomes so the
// traffic-light, low-confidence, and high-severity states are all reachable.
function mockDiagnose() {
  const outcomes = [
    {
      classId: "leaf_blight",
      name: "Leaf Blight (suspected)",
      confidence: 92,
      severity: "low",
      symptoms: "Browning starts at the leaf edges and spreads inward. Spreads quickly in humid conditions.",
      cause: "Excess soil moisture and poor airflow around the plant.",
      recommendations: [
        {
          product: "Mancozeb WP",
          reason: "Matches your growing environment and purpose; the pre-harvest interval clears before your expected harvest date.",
          usage: "Dilute 1:400, apply every 10 days, stop 14 days before harvest.",
        },
      ],
      excluded: [
        { product: "Systemic triazole fungicide", reason: "Excluded: its 21-day pre-harvest interval conflicts with your expected harvest date." },
      ],
    },
    {
      classId: "early_blight",
      name: "Early Blight",
      confidence: 88,
      severity: "medium",
      symptoms: "Dark concentric rings appear on older leaves first, then spread upward.",
      cause: "Warm, humid weather and water splashing soil onto lower leaves.",
      recommendations: [
        {
          product: "Chlorothalonil-based fungicide",
          reason: "Broad-spectrum control for this disease family, and its safety interval fits your harvest date.",
          usage: "Dilute 1:500, apply every 7–10 days, avoid spraying within 3 days of rain.",
        },
      ],
      excluded: [
        { product: "Copper hydroxide", reason: "Excluded: not certified for organic use under your current certification." },
      ],
    },
    {
      classId: "uncertain",
      name: null,
      confidence: 54,
      severity: "medium",
      symptoms: null,
      cause: null,
      recommendations: [],
      excluded: [],
    },
    {
      classId: "severe_rot",
      name: "Fruit Rot (advanced)",
      confidence: 81,
      severity: "very high",
      symptoms: "Soft, sunken lesions with visible spore masses have spread across most of the fruit.",
      cause: "Prolonged wet conditions combined with delayed removal of infected fruit.",
      recommendations: [
        {
          product: "Captan fungicide",
          reason: "Fast-acting against advanced rot and still within your pre-harvest safety window.",
          usage: "Dilute 1:300, apply immediately, repeat after 5 days if symptoms persist.",
        },
      ],
      excluded: [],
    },
  ];
  return outcomes[Math.floor(Math.random() * outcomes.length)];
}
