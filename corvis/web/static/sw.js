/* Corvis service worker. It makes Corvis installable as a phone app and shows a friendly
   page when the PC can't be reached. It never caches chats or API answers: everything
   always comes fresh from your PC. */
const CACHE = "corvis-shell-v1";
const OFFLINE = "/offline.html";
const KEEP = [OFFLINE, "/static/icon-192.png", "/static/mark.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(KEEP)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  // Only page loads get the offline fallback; everything else goes straight to the PC.
  if (event.request.mode !== "navigate") return;
  event.respondWith(fetch(event.request).catch(() => caches.match(OFFLINE)));
});
