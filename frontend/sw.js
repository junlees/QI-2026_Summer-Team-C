// Minimal service worker: makes the app installable and usable offline.
// Bump CACHE_NAME whenever precached files change so old caches get cleared.
const CACHE_NAME = "agrisage-v3";
const PRECACHE_URLS = [
  "/",
  "landing.html",
  "login.html",
  "signup.html",
  "dashboard.html",
  "crop-select.html",
  "diagnose.html",
  "diagnosis-result.html",
  "follow-up.html",
  "history.html",
  "mypage.html",
  "index.html",
  "css/styles.css",
  "js/store.js",
  "manifest.webmanifest",
  "icons/icon-192.png",
  "icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

// HTML, CSS, and JS are all network-first: always fetch the latest from the
// server when online (so edits show up on the very next load, not "one load
// later"), and fall back to the cached copy only when offline. Only icons
// and the manifest — which rarely change — are cache-first for speed.
self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const isHTML = req.mode === "navigate" || req.headers.get("accept")?.includes("text/html");
  const isCodeAsset = req.url.endsWith(".css") || req.url.endsWith(".js");

  if (isHTML || isCodeAsset) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
          return res;
        })
        .catch(() => caches.match(req).then((cached) => cached || caches.match("landing.html")))
    );
    return;
  }

  event.respondWith(
    caches.match(req).then((cached) => cached || fetch(req))
  );
});
