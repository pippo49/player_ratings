/*
 * Offline support: cache the whole bundle so the app works on match day
 * with no signal.
 *
 * Ratings change only when someone runs a scrape and commits, so the
 * strategy is network-first with a cache fallback: online you get the
 * freshest data, offline you get whatever was last seen. Bump CACHE_VERSION
 * to force clients onto a new shell.
 */

const CACHE_VERSION = "ratings-v1";
const SHELL = [
  "./",
  "./index.html",
  "./app.js",
  "./styles.css",
  "./ratings.json",
  "./manifest.json",
  "./icon-192.png",
  "./icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION)
      // Individual misses must not fail the whole install.
      .then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  // Never cache a scrape or its progress — those are live by definition.
  if (new URL(request.url).pathname.includes("/api/")) return;

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE_VERSION).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request).then(
        (hit) => hit || caches.match("./index.html")
      ))
  );
});
