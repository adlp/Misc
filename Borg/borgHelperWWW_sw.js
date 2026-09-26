// SW_VERSION: 1.0.0
// borgHelperWWW — Service Worker des notifications push (spec-push-ui-prefs-json).
// Servi par borgHelperWWW sur /sw.js (portée : toute l'origine). Ne fait qu'afficher les notifications
// envoyées par le serveur (watcher bkp_status ou POST /push/test) et ramener au premier plan l'onglet
// borgHelperWWW au clic — aucun cache hors-ligne, aucune interception de requête.
'use strict';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

function describe(d) {
  // Payload serveur : {nick, event: 'start'|'end'|'test', result: 'success'|'error'|null, timestamp}
  const nick = d.nick || '?';
  if (d.event === 'test') return {title: 'borgHelper — test', body: 'Les notifications fonctionnent.'};
  if (d.event === 'start') return {title: `Sauvegarde démarrée — ${nick}`, body: 'Bkp en cours.'};
  if (d.event === 'end' && d.result === 'success')
    return {title: `✅ Sauvegarde terminée — ${nick}`, body: 'Bkp réussi.'};
  if (d.event === 'end')
    return {title: `❌ Échec de sauvegarde — ${nick}`, body: 'Bkp en échec (ou interrompu). Voir borgHelperWWW.'};
  return {title: 'borgHelper', body: 'Notification reçue.'};
}

self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = {}; }
  const {title, body} = describe(d);
  let when = Date.now();
  if (d.timestamp) { const t = Date.parse(d.timestamp); if (!isNaN(t)) when = t; }
  e.waitUntil(self.registration.showNotification(title, {
    body,
    // Même tag par nick : une fin de sauvegarde remplace la notif de début au lieu de s'empiler.
    tag: d.nick ? `bkp-${d.nick}` : 'bkp-test',
    renotify: true,
    timestamp: when,
    data: d,
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
    for (const w of wins) { if ('focus' in w) return w.focus(); }
    if (self.clients.openWindow) return self.clients.openWindow('/');
  })());
});
