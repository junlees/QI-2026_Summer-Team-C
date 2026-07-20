// Registers the service worker so AgriSage is installable and works offline.
// Included on every page; safe to run even where the browser doesn't support it.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {
      // Installability is a progressive enhancement — ignore failures (e.g. non-HTTPS dev origins).
    });
  });
}
