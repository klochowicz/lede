// Minimal service worker: present so the app is installable. Deliberately no caching (v1).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {
  // Pass-through: let the network handle every request. Offline-first is out of scope for v1.
});
