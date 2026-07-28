// API layer for the AgriSage backend: JWT auth plus fetch-backed profile,
// crops, history, and diagnosis calls. Function names/shapes intentionally
// match the old localStorage mock so page code reads the same — but the data
// functions are now async (pages await them inside an init IIFE).

const TOKEN_KEY = "agrisage_token";

// One-time cleanup of the pre-auth localStorage mock data (profile/crops/
// history now live server-side; deliberately not migrated — it was demo data).
["agrisage_profile", "agrisage_crops", "agrisage_history"].forEach((k) => localStorage.removeItem(k));

// Escape untrusted strings (URL params, API fields) before innerHTML insertion.
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// --- auth ---------------------------------------------------------------
function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}
function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// Call first on every logged-in page. Redirects guests to the login page.
function requireAuth() {
  if (!getToken()) window.location.href = "login.html";
}

function logout() {
  clearToken();
  window.location.href = "landing.html";
}

// fetch() with the Bearer token attached. A 401 means the token is missing,
// expired, or references a wiped account — clear it and restart at login.
async function authFetch(path, opts = {}) {
  const headers = { ...(opts.headers || {}), Authorization: `Bearer ${getToken()}` };
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    clearToken();
    window.location.href = "login.html";
    throw new Error("Session expired. Please log in again.");
  }
  return res;
}

async function _readError(res, fallback) {
  let message = fallback;
  try {
    const body = await res.json();
    if (body.message) message = body.message;
  } catch (e) { /* non-JSON error body */ }
  return message;
}

async function apiSignup({ email, password, certification, purpose }) {
  const res = await fetch("/api/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, certification, purpose }),
  });
  if (!res.ok) throw new Error(await _readError(res, `Sign-up failed (HTTP ${res.status}).`));
  const body = await res.json();
  setToken(body.token);
  return mapProfile(body.profile);
}

async function apiLogin(email, password) {
  const res = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await _readError(res, `Login failed (HTTP ${res.status}).`));
  const body = await res.json();
  setToken(body.token);
  return mapProfile(body.profile);
}

// --- profile ------------------------------------------------------------
function mapProfile(p) {
  return {
    email: p.email,
    role: p.role,
    certification: p.certification,
    purpose: p.purpose,
    dailyLimit: p.daily_limit,
    usedToday: p.used_today,
  };
}

async function getProfile() {
  const res = await authFetch("/api/profile");
  if (!res.ok) throw new Error(await _readError(res, "Could not load your profile."));
  return mapProfile(await res.json());
}

async function saveProfile({ certification, purpose }) {
  const res = await authFetch("/api/profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ certification, purpose }),
  });
  if (!res.ok) throw new Error(await _readError(res, "Could not save your profile."));
  return mapProfile(await res.json());
}

// --- crops --------------------------------------------------------------
function mapCrop(c) {
  return {
    id: c.id,
    name: c.name,
    emoji: c.emoji,
    color: c.color,
    growingEnvironment: c.growing_environment,
    purposeOverride: c.purpose_override,
    harvestDate: c.harvest_date,
  };
}

async function getCrops() {
  const res = await authFetch("/api/crops");
  if (!res.ok) throw new Error(await _readError(res, "Could not load your crops."));
  return (await res.json()).map(mapCrop);
}

async function addCrop({ name, emoji, color, growingEnvironment, purposeOverride, harvestDate }) {
  const res = await authFetch("/api/crops", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name, emoji, color,
      growing_environment: growingEnvironment,
      purpose_override: purposeOverride,
      harvest_date: harvestDate,
    }),
  });
  if (!res.ok) throw new Error(await _readError(res, "Could not register the crop."));
  return mapCrop(await res.json());
}

async function updateCrop(id, { growingEnvironment, purposeOverride, harvestDate }) {
  const res = await authFetch(`/api/crops/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      growing_environment: growingEnvironment,
      purpose_override: purposeOverride,
      harvest_date: harvestDate,
    }),
  });
  if (!res.ok) throw new Error(await _readError(res, "Could not save the crop."));
  return mapCrop(await res.json());
}

async function removeCrop(id) {
  const res = await authFetch(`/api/crops/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await _readError(res, "Could not delete the crop."));
}

// A crop can override the account-level purpose (e.g. an organic grower
// selling most crops but keeping one for home use). The server applies the
// same chain during diagnosis and echoes it as effective_purpose — this
// client copy remains only for labels and legacy stored results.
function resolvePurpose(crop, profile) {
  return (crop && crop.purposeOverride) || (profile && profile.purpose) || "self_consumption";
}

// --- history ------------------------------------------------------------
async function getHistory() {
  const res = await authFetch("/api/history");
  if (!res.ok) throw new Error(await _readError(res, "Could not load your history."));
  // Server entries carry the raw API result; map it to the render shape the
  // pages expect (same mapping the live diagnosis flow uses).
  return (await res.json()).map((e) => ({ ...e, result: mapDiagnosisResponse(e.result) }));
}

async function findHistoryEntry(id) {
  const history = await getHistory();
  // Server ids are numbers; callers pass URL-param strings.
  return history.find((h) => String(h.id) === String(id)) || null;
}

async function updateFollowUp(id, followUpStatus) {
  const res = await authFetch(`/api/diagnose/${id}/follow-up`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ follow_up_status: followUpStatus }),
  });
  if (!res.ok) throw new Error(await _readError(res, "Could not save the follow-up."));
}

// --- admin --------------------------------------------------------------
async function adminListUsers() {
  const res = await authFetch("/api/admin/users");
  if (!res.ok) throw new Error(await _readError(res, "Could not load users."));
  return res.json();
}

async function adminSetLimit(userId, dailyLimit) {
  const res = await authFetch(`/api/admin/users/${userId}/limit`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ daily_limit: dailyLimit }),
  });
  if (!res.ok) throw new Error(await _readError(res, "Could not update the limit."));
  return res.json();
}

// --- diagnosis ----------------------------------------------------------
// Real AI diagnosis via POST /api/diagnose (leaf detection -> classifier ->
// knowledge base -> LLM explanation on the server). Personalization
// (certification/environment/purpose/harvest date) is resolved server-side
// from the account and the registered crop — only the photo, the crop id,
// and optional user notes travel in the request.
async function diagnoseWithApi({ imageBlob, cropId, userInput }) {
  const form = new FormData();
  // Always send a normalized ASCII filename — the backend's secure_filename()
  // strips non-ASCII names (e.g. Korean gallery filenames) down to nothing,
  // which would fail its extension check.
  const ext = imageBlob && imageBlob.type === "image/png" ? "png" : "jpg";
  form.append("image", imageBlob, `photo.${ext}`);
  if (cropId != null) form.append("crop_id", cropId);
  if (userInput) form.append("user_input", userInput);

  const res = await authFetch("/api/diagnose", { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(await _readError(res, `Diagnosis request failed (HTTP ${res.status}).`));
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
    // Purpose the server actually used for this diagnosis (override/account
    // chain at diagnosis time) — the PHI banner prefers this over the
    // *current* profile so history re-entries stay accurate.
    effectivePurpose: api.effective_purpose || null,
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
