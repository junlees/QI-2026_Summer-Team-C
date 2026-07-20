// Shared mock "backend" for the prototype: localStorage-backed profile/crops/
// history, plus a fake AI diagnosis call. Replace with real fetch() calls to
// the endpoints listed in CLAUDE.md once the backend implements them.

const STORE_KEYS = {
  profile: "agrisage_profile",
  crops: "agrisage_crops",
  history: "agrisage_history",
};

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

// Mock AI diagnosis: picks one of a few canned outcomes so the traffic-light,
// low-confidence, and high-severity states are all reachable in the demo.
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
