// Guarda el dibujo de la oficina en el teléfono para que abra al instante.
// El estado NUNCA se guarda: siempre se pide fresco a GitHub.
var CACHE = 'oficina-monitoreo-v1';
var FILES = ['./', './oficina.html', './manifest.webmanifest', './icon-180.png', './icon-192.png', './icon-512.png'];

self.addEventListener('install', function(e){
  e.waitUntil(caches.open(CACHE).then(function(c){ return c.addAll(FILES); }));
  self.skipWaiting();
});

self.addEventListener('activate', function(e){
  e.waitUntil(caches.keys().then(function(keys){
    return Promise.all(keys.filter(function(k){ return k !== CACHE; }).map(function(k){ return caches.delete(k); }));
  }));
  self.clients.claim();
});

self.addEventListener('fetch', function(e){
  if (e.request.method !== 'GET' || new URL(e.request.url).origin !== location.origin) return;   // GitHub API: directo
  e.respondWith(
    fetch(e.request).then(function(res){
      if (res.ok){ var copia = res.clone(); caches.open(CACHE).then(function(c){ c.put(e.request, copia); }); }
      return res;
    }).catch(function(){
      return caches.match(e.request).then(function(hit){ return hit || caches.match('./oficina.html'); });
    })
  );
});
