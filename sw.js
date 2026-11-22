// Start Times offline copy: always try the network first; if it's down, use the last copy saved.
const CACHE = "start-times-v1";
self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  // live sync and sign-in always go straight to the network
  if (/firebaseio\.com|identitytoolkit|securetoken|firebasedatabase/.test(url.host + url.pathname)) return;
  const sameSite = url.origin === self.location.origin;
  const key = sameSite ? url.origin + url.pathname : req.url;   // one copy per page, whatever ?v= it was opened with
  e.respondWith(
    fetch(req).then((res) => {
      if (res && (res.ok || res.type === "opaque")) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(key, copy)); }
      return res;
    }).catch(() => caches.match(key).then((hit) => hit || caches.match(req, { ignoreSearch: true })))
  );
});
