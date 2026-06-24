"""Ingress dashboard: a live face-recognition console.

Bound to 0.0.0.0 for ingress (HA authenticates it). All URLs are relative so they
work under the ingress token path. The handler calls into the App for everything:
a smooth MJPEG feed, a capture -> confirm -> save enrollment flow (raw image bytes
in the POST body, no multipart), and naming an unknown face straight from the log.
"""
from __future__ import annotations

import json
import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("local-faces.server")

# Single self-contained page. No external fonts/assets (ingress has no CDN).
# Design: a "porch-lantern" instrument panel - amber means someone you know is
# here; coral means a stranger. Monospace labels + system-sans names on a deep
# plum-ink screen. The hero is the live viewport itself.
PAGE = b"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local Faces</title>
<style>
  :root {
    color-scheme: light dark;
    --ground:#F1EEF3; --surface:#FFFFFF; --surface-2:#F7F5F9;
    --text:#221C2A; --muted:#6E6676; --border:rgba(34,28,42,.12);
    --accent:#E0A24C; --accent-text:#9A6614; --on-accent:#241803;
    --alert:#E2674A; --alert-text:#B23A22; --ok:#3FA98B;
    --screen:#0E0B12; --screen-text:#EDE7E1;
    --mono:ui-monospace,"SF Mono","Cascadia Mono","Roboto Mono",Menlo,Consolas,monospace;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
    --r:14px;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --ground:#19151F; --surface:#211C28; --surface-2:#1B1622;
      --text:#ECE6EE; --muted:#9A91A2; --border:rgba(236,230,238,.11);
      --accent-text:#E7B66B; --alert-text:#EC8A6E;
    }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--ground); color:var(--text);
         font-family:var(--sans); line-height:1.5;
         padding:18px; -webkit-font-smoothing:antialiased; }
  .wrap { max-width:940px; margin:0 auto; }

  .eyebrow { font-family:var(--mono); font-size:11px; letter-spacing:.16em;
             text-transform:uppercase; color:var(--muted); }

  /* Header / wordmark */
  .topbar { display:flex; align-items:center; justify-content:space-between;
            gap:12px; margin-bottom:16px; }
  .brand { display:flex; align-items:center; gap:11px; }
  .reticle { width:18px; height:18px; border:1.6px solid var(--accent);
             border-radius:4px; position:relative; flex:none; }
  .reticle::after { content:""; position:absolute; inset:5px; border-radius:1px;
                    background:var(--accent); }
  .brand b { font-family:var(--mono); font-size:14px; letter-spacing:.22em;
             text-transform:uppercase; font-weight:600; }
  .brand span { font-family:var(--mono); font-size:11px; letter-spacing:.14em;
                text-transform:uppercase; color:var(--muted); }
  .pill { display:inline-flex; align-items:center; gap:7px; font-family:var(--mono);
          font-size:11px; letter-spacing:.1em; text-transform:uppercase;
          color:var(--muted); background:var(--surface); border:1px solid var(--border);
          padding:6px 11px; border-radius:999px; }
  .pill .dot { width:7px; height:7px; border-radius:50%; background:var(--muted); }
  .pill.live .dot { background:var(--accent); animation:pulse 2s infinite; }
  .pill.alert .dot { background:var(--alert); }

  /* Hero viewport */
  .viewport { position:relative; aspect-ratio:16/9; background:var(--screen);
              border-radius:var(--r); overflow:hidden; border:1px solid var(--border);
              box-shadow:0 1px 0 var(--border); }
  .viewport::before { content:""; position:absolute; inset:0; z-index:3;
              pointer-events:none; border-top:3px solid transparent;
              transition:border-color .4s, box-shadow .4s; }
  .viewport.known::before { border-top-color:var(--accent);
              box-shadow:inset 0 14px 30px -16px var(--accent); }
  .viewport.unknown::before { border-top-color:var(--alert);
              box-shadow:inset 0 14px 30px -16px var(--alert); }
  .viewport img { width:100%; height:100%; object-fit:cover; display:block; }
  .scan { position:absolute; left:0; right:0; top:0; height:42%; z-index:2;
          background:linear-gradient(to bottom, transparent, rgba(224,162,76,.16));
          border-bottom:1px solid rgba(224,162,76,.5); opacity:0; }
  .viewport.watching .scan { opacity:1; animation:scan 3.6s linear infinite; }
  .vp-overlay { position:absolute; inset:0; z-index:4; display:none;
                flex-direction:column; align-items:center; justify-content:center;
                gap:6px; text-align:center; padding:24px; color:var(--screen-text); }
  .viewport.no-feed .vp-overlay { display:flex; }
  .vp-overlay .ttl { font-family:var(--mono); letter-spacing:.12em;
                     text-transform:uppercase; font-size:12px; }
  .vp-overlay .hint { font-size:13px; color:#B7AFC0; max-width:34ch; }
  .vp-status { position:absolute; left:0; right:0; bottom:0; z-index:4;
               display:flex; align-items:center; gap:10px; padding:12px 14px;
               color:var(--screen-text); font-family:var(--mono); font-size:12px;
               letter-spacing:.06em;
               background:linear-gradient(to top, rgba(0,0,0,.62), transparent); }
  .vp-status .who { color:var(--accent); text-transform:none; letter-spacing:0;
                    font-family:var(--sans); font-weight:600; font-size:14px; }
  .viewport.unknown .vp-status .who { color:var(--alert-text); }
  .vp-status .sep { color:#8c8696; }

  /* Body grid */
  .grid { display:grid; gap:14px; margin-top:14px;
          grid-template-columns:1fr 1fr;
          grid-template-areas:"enroll sightings" "people sightings"; }
  .enroll { grid-area:enroll; } .people { grid-area:people; }
  .sightings { grid-area:sightings; }
  @media (max-width:720px) {
    .grid { grid-template-columns:1fr;
            grid-template-areas:"enroll" "people" "sightings"; }
  }

  .card { background:var(--surface); border:1px solid var(--border);
          border-radius:var(--r); padding:16px; }
  .card > h2 { margin:0; font-family:var(--mono); font-size:11px; letter-spacing:.16em;
               text-transform:uppercase; color:var(--muted); font-weight:600; }
  .card .lead { margin:4px 0 14px; font-size:13px; color:var(--muted); }

  /* Enroll */
  .field { display:flex; flex-direction:column; gap:7px; }
  label.lbl { font-family:var(--mono); font-size:11px; letter-spacing:.1em;
              text-transform:uppercase; color:var(--muted); }
  input[type=text] { font:inherit; padding:10px 12px; border-radius:10px;
                     background:var(--surface-2); color:var(--text);
                     border:1px solid var(--border); width:100%; }
  input[type=text]:focus-visible { outline:2px solid var(--accent); outline-offset:1px; }
  .btns { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
  button { font:inherit; font-weight:600; padding:10px 15px; border-radius:10px;
           border:1px solid transparent; cursor:pointer; }
  button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
  .btn-primary { background:var(--accent); color:var(--on-accent); }
  .btn-primary:hover { filter:brightness(1.05); }
  .btn-ghost { background:transparent; color:var(--text); border-color:var(--border); }
  .btn-ghost:hover { background:var(--surface-2); }
  button:disabled { opacity:.5; cursor:default; filter:none; }
  .msg { margin-top:11px; font-size:13px; min-height:1.25em; color:var(--muted); }
  .msg.ok { color:var(--accent-text); } .msg.err { color:var(--alert-text); }

  .review { display:none; gap:13px; align-items:flex-start; margin-top:4px; }
  .review.show { display:flex; }
  .review img { width:76px; height:76px; border-radius:10px; object-fit:cover;
                border:2px solid var(--accent); flex:none; }
  .review .rc { flex:1; min-width:0; }

  /* Lists (people + sightings) */
  ul.list { list-style:none; padding:0; margin:14px 0 0; }
  ul.list .empty { color:var(--muted); font-size:13px; padding:6px 0; }
  .item { display:flex; align-items:center; gap:11px; padding:10px 0;
          border-top:1px solid var(--border); }
  .item:first-child { border-top:0; }
  .thumb { width:42px; height:42px; border-radius:9px; object-fit:cover; flex:none;
           background:var(--surface-2); border:1px solid var(--border); }
  .thumb.unknown { border-color:var(--alert); }
  .col { flex:1; min-width:0; }
  .col .name { font-weight:600; font-size:14px; }
  .col .name.is-unknown { color:var(--alert-text); }
  .col .meta { font-family:var(--mono); font-size:11px; color:var(--muted);
               letter-spacing:.04em; }
  .badge { font-family:var(--mono); font-size:10px; letter-spacing:.08em;
           text-transform:uppercase; padding:3px 8px; border-radius:999px; }
  .badge.known { color:var(--accent-text); border:1px solid var(--accent); }
  .badge.unknown { color:var(--alert-text); border:1px solid var(--alert); }
  .link { background:none; border:0; padding:6px 8px; color:var(--accent-text);
          font-family:var(--mono); font-size:11px; letter-spacing:.06em;
          text-transform:uppercase; cursor:pointer; font-weight:600; }
  .link:hover { text-decoration:underline; }
  .link.danger { color:var(--alert-text); }
  .nameform { display:flex; gap:7px; width:100%; margin-top:8px; }
  .nameform input { flex:1; }

  @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:.35;} }
  @keyframes scan { from{transform:translateY(-100%);} to{transform:translateY(240%);} }
  @media (prefers-reduced-motion: reduce) {
    .pill.live .dot { animation:none; }
    .viewport.watching .scan { animation:none; opacity:0; }
  }
</style>
</head>
<body>
<div class="wrap">

  <div class="topbar">
    <div class="brand">
      <span class="reticle"></span>
      <b>Local Faces</b>
      <span>on-device</span>
    </div>
    <span class="pill" id="pill"><span class="dot"></span><span id="pillText">Starting</span></span>
  </div>

  <div class="viewport no-feed" id="viewport">
    <img id="feed" alt="Live camera view">
    <div class="scan"></div>
    <div class="vp-overlay">
      <div class="ttl" id="ovTitle">Waiting for the camera</div>
      <div class="hint" id="ovHint">The live view appears here once your camera connects.</div>
    </div>
    <div class="vp-status">
      <span id="vpState">Idle</span>
      <span class="sep">/</span>
      <span id="vpFaces">0 faces</span>
      <span class="who" id="vpWho"></span>
    </div>
  </div>

  <div class="grid">

    <section class="card enroll">
      <h2>Enroll a face</h2>
      <p class="lead">Capture from the live camera or upload a clear photo, then give
         it a name. A few angles per person works best.</p>

      <div class="field">
        <label class="lbl" for="name">Name</label>
        <input type="text" id="name" placeholder="e.g. Alex" autocomplete="off">
      </div>

      <div class="btns" id="captureBtns">
        <button class="btn-primary" id="capture">Capture from camera</button>
        <button class="btn-ghost" id="pick">Upload photo</button>
        <input type="file" id="file" accept="image/*" hidden>
      </div>

      <div class="review" id="review">
        <img id="reviewThumb" alt="Captured face">
        <div class="rc">
          <div class="lbl">Captured face</div>
          <div class="btns" style="margin-top:8px">
            <button class="btn-primary" id="save">Save face</button>
            <button class="btn-ghost" id="retake">Discard</button>
          </div>
        </div>
      </div>

      <div class="msg" id="msg" aria-live="polite">&nbsp;</div>
    </section>

    <section class="card people">
      <h2>Known people</h2>
      <ul class="list" id="people"></ul>
    </section>

    <section class="card sightings">
      <h2>Recent sightings</h2>
      <p class="lead">Every recognized and unknown face. See an unknown you know?
         Name it here and they'll be recognized next time.</p>
      <ul class="list" id="log"></ul>
    </section>

  </div>
</div>

<script>
(function(){
  var pendingToken = null;

  function el(id){ return document.getElementById(id); }
  function setMsg(t, kind){ var m=el("msg"); m.textContent=t||"\\u00a0";
    m.className="msg"+(kind?(" "+kind):""); }
  function fmtTime(t){ return t ? new Date(t*1000).toLocaleString() : "-"; }
  function pct(s){ return Math.round(s*100)+"%"; }

  function api(path, opts){
    return fetch(path, Object.assign({cache:"no-store"}, opts||{}))
      .then(function(r){ return r.json(); });
  }
  function busy(ids, on){ ids.forEach(function(id){ el(id).disabled=on; }); }

  // ---- live feed + status ----
  // Poll a single JPEG rather than an MJPEG stream: HA's ingress proxy does not
  // pass multipart/x-mixed-replace, so an <img src="stream.mjpeg"> renders broken
  // under ingress. Preload each frame and swap on load so we never flash the
  // browser's broken-image icon between updates or while the camera reconnects.
  (function(){
    var feed = el("feed");
    function tick(){
      var probe = new Image();
      probe.onload = function(){ feed.src = probe.src; };
      probe.src = "preview.jpg?t=" + Date.now();
    }
    tick();
    setInterval(tick, 500);
  })();

  function refreshStatus(){
    api("status").then(function(s){
      var vp=el("viewport");
      vp.classList.toggle("no-feed", !s.camera_ok);
      vp.classList.toggle("watching", !!s.camera_ok);
      vp.classList.toggle("known", s.state==="known");
      vp.classList.toggle("unknown", s.state==="unknown");

      if(!s.stream_set){
        el("ovTitle").textContent="No camera connected";
        el("ovHint").textContent="Set your camera's URL on the Configuration tab, then restart.";
      } else if(!s.camera_ok){
        el("ovTitle").textContent="Connecting to the camera";
        el("ovHint").textContent=
          "Hang tight \\u2014 the live view starts as soon as frames arrive.";
      }

      var pill=el("pill");
      pill.className="pill"+(s.camera_ok?" live":(s.stream_set?" alert":""));
      el("pillText").textContent = s.camera_ok ? "Live"
        : (s.stream_set ? "No signal" : "Set up camera");

      el("vpState").textContent = s.state==="known" ? "Recognized"
        : (s.state==="unknown" ? "Unknown face" : "Watching");
      el("vpFaces").textContent = s.faces + (s.faces===1?" face":" faces");
      el("vpWho").textContent = (s.state==="known" && s.recognized)
        ? (s.recognized + "  " + pct(s.score)) : "";
    }).catch(function(){});
  }

  // ---- known people ----
  function refreshPeople(){
    api("people").then(function(d){
      var ul=el("people"); ul.innerHTML="";
      if(!d.people.length){
        var li=document.createElement("li");
        li.className="empty"; li.textContent="Nobody enrolled yet. Capture a face to begin.";
        ul.appendChild(li); return;
      }
      d.people.forEach(function(p){
        var li=document.createElement("li"); li.className="item";
        li.appendChild(makeThumb(p.thumb, false));
        var col=document.createElement("div"); col.className="col";
        var nm=document.createElement("div"); nm.className="name"; nm.textContent=p.name;
        var meta=document.createElement("div"); meta.className="meta";
        meta.textContent=p.samples+(p.samples===1?" sample":" samples");
        col.appendChild(nm); col.appendChild(meta); li.appendChild(col);
        var del=document.createElement("button"); del.className="link danger";
        del.textContent="Remove";
        del.addEventListener("click", function(){
          if(!confirm("Remove "+p.name+"?")) return;
          api("person/delete?name="+encodeURIComponent(p.name), {method:"POST"})
            .then(function(r){ setMsg(r.message, r.ok?"ok":"err");
              refreshPeople(); refreshLog(); });
        });
        li.appendChild(del); ul.appendChild(li);
      });
    }).catch(function(){});
  }

  function makeThumb(b64, unknown){
    if(b64){ var im=document.createElement("img"); im.className="thumb"+(unknown?" unknown":"");
      im.src="data:image/jpeg;base64,"+b64; im.alt=""; return im; }
    var sp=document.createElement("span"); sp.className="thumb"+(unknown?" unknown":""); return sp;
  }

  // ---- sightings log (with name-from-log) ----
  function refreshLog(){
    api("log").then(function(d){
      var ul=el("log"); ul.innerHTML="";
      if(!d.events.length){
        var li=document.createElement("li");
        li.className="empty"; li.textContent="No sightings yet.";
        ul.appendChild(li); return;
      }
      d.events.forEach(function(e){
        var li=document.createElement("li"); li.className="item";
        li.appendChild(makeThumb(e.thumb, e.unknown));
        var col=document.createElement("div"); col.className="col";
        var top=document.createElement("div");
        var nm=document.createElement("span");
        nm.className="name"+(e.unknown?" is-unknown":"");
        nm.textContent=e.unknown?"Unknown":e.name; nm.style.marginRight="8px";
        top.appendChild(nm);
        var badge=document.createElement("span");
        badge.className="badge "+(e.unknown?"unknown":"known");
        badge.textContent=e.unknown?"new":pct(e.score);
        top.appendChild(badge);
        var meta=document.createElement("div"); meta.className="meta";
        meta.textContent=fmtTime(e.ts);
        col.appendChild(top); col.appendChild(meta); li.appendChild(col);

        if(e.unknown){
          var name=document.createElement("button"); name.className="link";
          name.textContent="Name";
          name.addEventListener("click", function(){ openNameForm(li, col, e.id, name); });
          li.appendChild(name);
        }
        ul.appendChild(li);
      });
    }).catch(function(){});
  }

  function openNameForm(li, col, id, trigger){
    trigger.style.display="none";
    var form=document.createElement("div"); form.className="nameform";
    var input=document.createElement("input"); input.type="text";
    input.placeholder="Who is this?";
    var save=document.createElement("button");
    save.className="btn-primary"; save.textContent="Save";
    var cancel=document.createElement("button");
    cancel.className="btn-ghost"; cancel.textContent="X";
    form.appendChild(input); form.appendChild(save); form.appendChild(cancel);
    col.appendChild(form); input.focus();
    function close(){ form.remove(); trigger.style.display=""; }
    cancel.addEventListener("click", close);
    function submit(){
      var n=input.value.trim(); if(!n){ input.focus(); return; }
      save.disabled=true;
      api("sighting/name?id="+encodeURIComponent(id)+"&name="+encodeURIComponent(n),
          {method:"POST"}).then(function(r){
        setMsg(r.message, r.ok?"ok":"err");
        if(r.ok){ refreshPeople(); refreshLog(); } else { save.disabled=false; }
      });
    }
    save.addEventListener("click", submit);
    input.addEventListener("keydown", function(ev){ if(ev.key==="Enter") submit(); });
  }

  // ---- enrollment: capture/upload -> review -> save ----
  function showReview(thumbB64, token){
    pendingToken=token;
    el("reviewThumb").src="data:image/jpeg;base64,"+thumbB64;
    el("review").classList.add("show");
    el("captureBtns").style.display="none";
    el("name").focus();
  }
  function resetEnroll(){
    pendingToken=null;
    el("review").classList.remove("show");
    el("captureBtns").style.display="";
  }
  function stage(promise, ids){
    busy(ids, true); setMsg("Looking for a face\\u2026");
    promise.then(function(r){
      busy(ids, false);
      if(r.ok && r.token){ setMsg(r.message, "ok"); showReview(r.thumb, r.token); }
      else { setMsg(r.message, "err"); }
    }).catch(function(){ busy(ids,false); setMsg("Something went wrong. Try again.","err"); });
  }

  el("capture").addEventListener("click", function(){
    stage(api("enroll/capture", {method:"POST"}), ["capture","pick"]);
  });
  el("pick").addEventListener("click", function(){ el("file").click(); });
  el("file").addEventListener("change", function(){
    var f=this.files[0]; if(!f) return;
    stage(api("enroll/upload", {method:"POST", body:f}), ["capture","pick"]);
    this.value="";
  });
  el("save").addEventListener("click", function(){
    var n=el("name").value.trim();
    if(!n){ setMsg("Enter a name first.","err"); el("name").focus(); return; }
    if(!pendingToken){ resetEnroll(); return; }
    busy(["save","retake"], true);
    api("enroll/commit?token="+encodeURIComponent(pendingToken)+"&name="+encodeURIComponent(n),
        {method:"POST"}).then(function(r){
      busy(["save","retake"], false); setMsg(r.message, r.ok?"ok":"err");
      if(r.ok){ el("name").value=""; resetEnroll(); refreshPeople(); refreshLog(); }
    }).catch(function(){ busy(["save","retake"],false); setMsg("Save failed. Try again.","err"); });
  });
  el("retake").addEventListener("click", function(){
    if(pendingToken){
      api("enroll/cancel?token="+encodeURIComponent(pendingToken), {method:"POST"});
    }
    resetEnroll(); setMsg("");
  });

  refreshStatus(); refreshPeople(); refreshLog();
  setInterval(refreshStatus, 1200);
  setInterval(refreshLog, 5000);
  setInterval(refreshPeople, 15000);
})();
</script>
</body>
</html>"""


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

        def _param(self, key):
            return (parse_qs(urlparse(self.path).query).get(key, [""])[0]).strip()

        def _body(self) -> bytes:
            length = int(self.headers.get("Content-Length", 0) or 0)
            return self.rfile.read(length) if length else b""

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            try:
                while app.running:
                    jpeg = app.preview_jpeg()
                    if jpeg:
                        self.wfile.write(b"--frame\r\n")
                        self.wfile.write(b"Content-Type: image/jpeg\r\n")
                        self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode())
                        self.wfile.write(jpeg)
                        self.wfile.write(b"\r\n")
                    time.sleep(0.4)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/enroll/capture":
                self._json(app.stage_from_frame())
            elif path == "/enroll/upload":
                self._json(app.stage_from_image(self._body()))
            elif path == "/enroll/commit":
                self._json(app.commit_enrollment(self._param("token"), self._param("name")))
            elif path == "/enroll/cancel":
                self._json(app.cancel_enrollment(self._param("token")))
            elif path == "/sighting/name":
                self._json(app.name_sighting(self._param("id"), self._param("name")))
            elif path == "/person/delete":
                self._json(app.delete_person(self._param("name")))
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
            elif path == "/stream.mjpeg":
                self._stream()
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
