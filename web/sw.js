const CACHE_NAME = "birdnet-v1";
const APP_SHELL = [
  "/",
  "/index.html",
  "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.js",
  "https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js",
  "https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3/dist/chartjs-plugin-annotation.min.js",
  "https://cdn.jsdelivr.net/npm/suncalc@1/suncalc.js",
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Stale-while-revalidate: serve from cache first, update cache in background
self.addEventListener("fetch", event => {
  // Only handle GET requests
  if (event.request.method !== "GET") return;
  // Skip cross-origin requests that aren't CDN (e.g. Supabase API calls)
  const url = new URL(event.request.url);
  const isAppShell = url.origin === self.location.origin || url.hostname.includes("jsdelivr.net");
  if (!isAppShell) return;

  event.respondWith(
    caches.open(CACHE_NAME).then(cache =>
      cache.match(event.request).then(cached => {
        const fresh = fetch(event.request).then(response => {
          if (response && response.status === 200) {
            cache.put(event.request, response.clone());
          }
          return response;
        }).catch(() => cached);
        return cached || fresh;
      })
    )
  );
});

// Handle push notifications
self.addEventListener("push", event => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { species: "Bird detected" };
  }
  const title = `🐦 ${data.common_name || data.species || "Bird detected"}`;
  const body  = data.confidence
    ? `Detected with ${(data.confidence * 100).toFixed(0)}% confidence`
    : "A bird was just detected";

  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      tag: "birdnet-detection",
    })
  );
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  event.waitUntil(
    clients.openWindow("/")
  );
});
