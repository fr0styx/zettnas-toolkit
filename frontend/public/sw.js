/* ZettNAS service worker (M1): makes the app installable, shows an offline notice,
 * and receives files from the phone's share sheet into the user's Inbox folder.
 * It never caches API responses or files. */
const OFFLINE_HTML =
  '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">' +
  '<title>ZettNAS offline</title><body><h1>ZettNAS is not reachable</h1>' +
  '<p>Check that you are on your home network or connected through Tailscale, then reload.</p></body>';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (req.method === 'POST' && url.pathname === '/share-target') {
    event.respondWith(receiveShare(req));
    return;
  }
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(() => new Response(OFFLINE_HTML, { headers: { 'Content-Type': 'text/html; charset=utf-8' } }))
    );
  }
});

async function upload(name, body, type) {
  return fetch(`/api/fs/inbox?filename=${encodeURIComponent(name)}`, {
    method: 'POST',
    body,
    credentials: 'same-origin',
    headers: { 'Content-Type': type || 'application/octet-stream' },
  });
}

async function receiveShare(request) {
  let form;
  try {
    form = await request.formData();
  } catch (e) {
    return Response.redirect('/?shared=error', 303);
  }
  const files = form.getAll('files').filter((f) => f && typeof f === 'object' && f.name);
  const text = ['title', 'text', 'url'].map((k) => form.get(k)).filter(Boolean).join('\n');
  let saved = 0;
  let failed = 0;
  const items = files.map((f) => [f.name, f, f.type]);
  if (!items.length && text) {
    const stamp = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-');
    items.push([`Shared note ${stamp}.txt`, new Blob([text], { type: 'text/plain' }), 'text/plain']);
  }
  for (const [name, body, type] of items) {
    const res = await upload(name, body, type).catch(() => null);
    if (res && res.status === 401) return Response.redirect('/?shared=login', 303);
    if (res && res.ok) saved += 1;
    else failed += 1;
  }
  return Response.redirect(`/?shared=${saved}&failed=${failed}`, 303);
}
