"""Ingress dashboard: live view, enroll people, and review the recognition log.

Bound to 0.0.0.0 for ingress (HA authenticates it). URLs are relative so they work
under the ingress token path. The handler calls into the App for everything;
enrollment uploads send the raw image bytes as the POST body (no multipart needed).
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("local-faces.server")

PAGE = b"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Local Faces</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin: 0; padding: 20px; max-width: 760px; }
  h1 { font-size: 1.3rem; margin: 0 0 2px; }
  .sub { opacity:.7; font-size:.85rem; margin:0 0 16px; }
  h2 { font-size: 1rem; margin: 22px 0 8px; }
  .frame { border-radius: 10px; overflow: hidden; background:#0006; aspect-ratio:16/9;
           display:grid; place-items:center; }
  .frame img { width:100%; height:100%; object-fit:contain; display:block; }
  .frame .empty { opacity:.5; font-size:.9rem; padding:20px; text-align:center; }
  .status { font-size:.85rem; opacity:.85; margin:10px 0; min-height:1.2em; }
  .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  input[type=text] { font:inherit; padding:9px 11px; border-radius:8px;
                     border:1px solid #8884; flex:1 1 160px; min-width:0; }
  button { font:inherit; font-weight:600; padding:9px 14px; border:0; border-radius:8px;
           background:#2f7; color:#042; cursor:pointer; }
  button.ghost { background:#8883; color:inherit; }
  button:disabled { opacity:.5; cursor:default; }
  .msg { font-size:.85rem; margin:8px 0; min-height:1.2em; }
  .people, .log { list-style:none; padding:0; margin:8px 0; }
  .people li, .log li { display:flex; align-items:center; gap:10px; padding:8px 0;
                        border-bottom:1px solid #8882; }
  .thumb { width:44px; height:44px; border-radius:6px; object-fit:cover; background:#8883;
           flex:none; }
  .grow { flex:1; }
  .name { font-weight:600; }
  .meta { font-size:.78rem; opacity:.65; }
  .tag { font-size:.72rem; padding:2px 7px; border-radius:99px; }
  .tag.known { background:#2f74; }
  .tag.unknown { background:#f445; }
</style></head><body>
  <h1>Local Faces</h1>
  <p class="sub">On-device face recognition. Enrollment, recognition, and the log
     stay on this box.</p>

  <div class="frame"><span class="empty" id="empty">Waiting for camera...</span>
       <img id="prev" alt="" hidden></div>
  <div class="status" id="status">&nbsp;</div>

  <h2>Enroll a face</h2>
  <p class="sub" style="margin-top:0">Type a name, then capture from the live camera
     or upload a clear photo. Add a few per person for best results.</p>
  <div class="row">
    <input type="text" id="name" placeholder="Name (e.g. Alex)" autocomplete="off">
    <button id="capture">Capture from camera</button>
    <button class="ghost" id="pick">Upload photo</button>
    <input type="file" id="file" accept="image/*" hidden>
  </div>
  <div class="msg" id="msg">&nbsp;</div>

  <h2>Enrolled people</h2>
  <ul class="people" id="people"></ul>

  <h2>Recent recognitions</h2>
  <ul class="log" id="log"></ul>

<script>
  function fmt(t){ return t ? new Date(t*1000).toLocaleString() : '-'; }
  function msg(t, ok){ var m=document.getElementById('msg'); m.textContent=t;
    m.style.color = ok===false ? '#e55' : (ok ? '#2b7' : 'inherit'); }

  function refreshPreview(ts){
    var img=document.getElementById('prev');
    img.src='preview.jpg?t='+ts; img.hidden=false;
    document.getElementById('empty').style.display='none';
  }
  function refreshStatus(){
    fetch('status',{cache:'no-store'}).then(r=>r.json()).then(s=>{
      if(s.camera_ok) refreshPreview(Math.floor(s.last_ts||Date.now()/1000));
      var parts=[];
      parts.push(s.stream_set ? (s.camera_ok?'Camera live':'Connecting to camera...')
                              : 'No camera configured - set stream_url');
      parts.push(s.faces+' face(s) now');
      parts.push(s.recognized ? ('recognized: '+s.recognized) : 'none recognized');
      parts.push(s.people+' enrolled');
      parts.push('MQTT '+(s.mqtt?'on':'off'));
      document.getElementById('status').textContent = parts.join(' \\u2022 ');
    }).catch(()=>{});
  }
  function refreshPeople(){
    fetch('people',{cache:'no-store'}).then(r=>r.json()).then(d=>{
      var ul=document.getElementById('people'); ul.innerHTML='';
      if(!d.people.length){ ul.innerHTML='<li class="meta">Nobody enrolled yet.</li>'; return; }
      d.people.forEach(p=>{
        var li=document.createElement('li');
        var img = p.thumb ? '<img class="thumb" src="data:image/jpeg;base64,'+p.thumb+'">'
                          : '<span class="thumb"></span>';
        li.innerHTML = img +
          '<span class="grow"><span class="name">'+p.name+'</span>'+
          '<div class="meta">'+p.samples+' sample(s)</div></span>'+
          '<button class="ghost" data-del="'+encodeURIComponent(p.name)+'">Remove</button>';
        ul.appendChild(li);
      });
      ul.querySelectorAll('[data-del]').forEach(b=>{
        b.onclick=()=>{ if(!confirm('Remove this person?')) return;
          fetch('person/delete?name='+b.dataset.del,{method:'POST'})
            .then(r=>r.json()).then(r=>{ msg(r.message, r.ok); refreshPeople(); }); };
      });
    }).catch(()=>{});
  }
  function refreshLog(){
    fetch('log',{cache:'no-store'}).then(r=>r.json()).then(d=>{
      var ul=document.getElementById('log'); ul.innerHTML='';
      if(!d.events.length){ ul.innerHTML='<li class="meta">No recognitions yet.</li>'; return; }
      d.events.forEach(e=>{
        var li=document.createElement('li');
        var img = e.thumb ? '<img class="thumb" src="data:image/jpeg;base64,'+e.thumb+'">'
                          : '<span class="thumb"></span>';
        var tag = e.unknown ? '<span class="tag unknown">unknown</span>'
                            : '<span class="tag known">'+Math.round(e.score*100)+'%</span>';
        li.innerHTML = img +
          '<span class="grow"><span class="name">'+e.name+'</span> '+tag+
          '<div class="meta">'+fmt(e.ts)+'</div></span>';
        ul.appendChild(li);
      });
    }).catch(()=>{});
  }

  function nameOrWarn(){
    var n=document.getElementById('name').value.trim();
    if(!n){ msg('Enter a name first.', false); return null; }
    return encodeURIComponent(n);
  }
  document.getElementById('capture').onclick=function(){
    var n=nameOrWarn(); if(!n) return;
    msg('Capturing...');
    fetch('enroll/frame?name='+n,{method:'POST'}).then(r=>r.json())
      .then(r=>{ msg(r.message, r.ok); refreshPeople(); }).catch(()=>msg('Failed.', false));
  };
  document.getElementById('pick').onclick=()=>document.getElementById('file').click();
  document.getElementById('file').onchange=function(){
    var n=nameOrWarn(); if(!n){ this.value=''; return; }
    var f=this.files[0]; if(!f) return;
    msg('Uploading...');
    fetch('enroll/upload?name='+n,{method:'POST',body:f}).then(r=>r.json())
      .then(r=>{ msg(r.message, r.ok); refreshPeople(); }).catch(()=>msg('Failed.', false));
    this.value='';
  };

  refreshStatus(); refreshPeople(); refreshLog();
  setInterval(refreshStatus, 1500);
  setInterval(refreshLog, 4000);
</script></body></html>"""


def make_server(app, host: str = "0.0.0.0", port: int = 8099):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.debug("%s - %s", self.address_string(), fmt % args)

        def _send(self, code, ctype, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, "application/json", json.dumps(obj).encode())

        def _name(self):
            return (parse_qs(urlparse(self.path).query).get("name", [""])[0]).strip()

        def _body(self) -> bytes:
            length = int(self.headers.get("Content-Length", 0) or 0)
            return self.rfile.read(length) if length else b""

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/enroll/frame":
                self._json(app.enroll_from_frame(self._name()))
            elif path == "/enroll/upload":
                self._json(app.enroll_from_image(self._name(), self._body()))
            elif path == "/person/delete":
                self._json(app.delete_person(self._name()))
            else:
                self._send(404, "text/plain", b"not found")

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", ""):
                self._send(200, "text/html; charset=utf-8", PAGE)
            elif path == "/status":
                self._json(app.public_status())
            elif path == "/people":
                self._json({"people": app.db.people()})
            elif path == "/log":
                self._json({"events": app.reclog.recent()})
            elif path == "/preview.jpg":
                jpeg = app.preview_jpeg()
                if jpeg:
                    self._send(200, "image/jpeg", jpeg)
                else:
                    self._send(503, "text/plain", b"no frame yet")
            else:
                self._send(404, "text/plain", b"not found")

        do_HEAD = do_GET

    return ThreadingHTTPServer((host, port), Handler)
