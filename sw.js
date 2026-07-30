/* Calculator service worker — precache + stale-while-revalidate.
   Loads are always served from cache instantly; the network refreshes the
   cache in the background so the next open picks up updates. */

const VERSION = 'nebula-v4';
// No './' entry — hosts without directory indexes (e.g. raw.githack.com) 404 on
// it; navigations fall back to the cached index.html instead.
const ASSETS = [
  'index.html',
  'styles.css',
  'js/app.js',
  'js/calc.js',
  'js/rules.js',
  'js/journal.js',
  'manifest.webmanifest',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/icon-maskable-512.png',
  'icons/apple-touch-icon.png',
];

self.addEventListener('install', e => {
  // Cache assets individually — one missing file must not abort the install.
  e.waitUntil(
    caches.open(VERSION)
      .then(c => Promise.allSettled(ASSETS.map(a => c.add(a))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return; // rate APIs etc: network only
  e.respondWith(
    caches.open(VERSION).then(async cache => {
      let cached = await cache.match(e.request, { ignoreSearch: true });
      if (!cached && e.request.mode === 'navigate') cached = await cache.match('index.html');
      const refresh = fetch(e.request)
        .then(res => {
          if (res && res.ok) cache.put(e.request, res.clone());
          return res;
        })
        .catch(() => null);
      e.waitUntil(refresh); // keep the background refresh alive past the response
      return cached || refresh.then(res => res || new Response('offline', { status: 503 }));
    })
  );
});
