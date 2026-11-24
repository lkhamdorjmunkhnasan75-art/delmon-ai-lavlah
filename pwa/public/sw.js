// Network-only: never cache directory responses or expired provenance.
self.addEventListener("install",()=>self.skipWaiting());
self.addEventListener("activate",event=>event.waitUntil(self.clients.claim()));
self.addEventListener("fetch",event=>{
 if(event.request.method==="GET" && event.request.mode==="navigate" && new URL(event.request.url).origin===self.location.origin){
  event.respondWith(fetch(event.request).catch(()=>new Response("Интернэт холболтоо шалгана уу.",{status:503,headers:{"Content-Type":"text/plain; charset=utf-8","Cache-Control":"no-store"}})));
 }
});
