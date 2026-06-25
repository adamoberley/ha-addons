"""Ingress dashboard: a live multi-camera face-recognition console.

Bound to 0.0.0.0 for ingress (HA authenticates it). All URLs are relative so they
work under the ingress token path. The handler calls into the App for everything:
a polled JPEG per camera (ingress doesn't pass MJPEG), capture -> confirm -> save
enrollment (raw image bytes in the POST body, no multipart), and naming an unknown
face straight from the log.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("local-faces.server")

# Single self-contained page. No external fonts/assets (ingress has no CDN).
PAGE = b"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local Faces</title>
<style>
  :root {
    color-scheme: light dark;
    --primary:#03a9f4; --primary-soft:rgba(3,169,244,.08);
    --bg:#f5f5f5; --card:#ffffff; --field:#fafafa;
    --text:#212121; --secondary:#727272; --divider:rgba(0,0,0,.12);
    --success:#43a047; --error:#db4437;
    --screen:#202124; --screen-text:#f1f1f1;
    --shadow:0 2px 1px -1px rgba(0,0,0,.2),0 1px 1px 0 rgba(0,0,0,.14),0 1px 3px 0 rgba(0,0,0,.12);
    --card-border:transparent;
    --sans:Roboto,"Helvetica Neue",-apple-system,system-ui,"Segoe UI",Arial,sans-serif;
    --r:12px;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#111111; --card:#1c1c1c; --field:#262626;
      --text:#e1e1e1; --secondary:#9b9b9b; --divider:rgba(225,225,225,.12);
      --shadow:none; --card-border:rgba(225,225,225,.12);
    }
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text);
         font-family:var(--sans); line-height:1.5;
         padding:16px; -webkit-font-smoothing:antialiased; }
  .wrap { max-width:1200px; margin:0 auto; }

  .topbar { display:flex; align-items:center; justify-content:space-between;
            gap:12px; margin:4px 4px 16px; }
  .brand { display:flex; align-items:center; gap:12px; }
  .reticle { width:22px; height:22px; border:2px solid var(--primary);
             border-radius:6px; position:relative; flex:none; }
  .reticle::after { content:""; position:absolute; inset:6px; border-radius:2px;
                    background:var(--primary); }
  .brand b { font-size:20px; font-weight:500; }
  .brand span { font-size:13px; color:var(--secondary); }
  .pill { display:inline-flex; align-items:center; gap:8px; font-size:13px;
          color:var(--secondary); background:var(--card); border:1px solid var(--divider);
          padding:6px 12px; border-radius:999px; }
  .pill .dot { width:8px; height:8px; border-radius:50%; background:var(--secondary); }
  .pill.live .dot { background:var(--success); animation:pulse 2s infinite; }
  .pill.alert .dot { background:var(--error); }

  /* Camera tiles */
  .cams { display:grid; gap:16px;
          grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); }
  .cam { position:relative; aspect-ratio:16/9; background:var(--screen);
         border-radius:var(--r); overflow:hidden; box-shadow:var(--shadow);
         border:1px solid var(--card-border); }
  .cam::before { content:""; position:absolute; inset:0; z-index:3; pointer-events:none;
                 border-top:3px solid transparent; transition:border-color .4s; }
  .cam.known::before { border-top-color:var(--success); }
  .cam.unknown::before { border-top-color:var(--error); }
  .cam img { width:100%; height:100%; object-fit:contain; display:block; }
  .cam.offline img { opacity:.25; }
  .cam .cap { position:absolute; top:10px; right:10px; z-index:5; font:inherit;
              font-size:13px; font-weight:500; padding:6px 12px; border-radius:8px;
              border:0; background:rgba(0,0,0,.55); color:#fff; cursor:pointer; }
  .cam .cap:hover { background:rgba(0,0,0,.75); }
  .cam .cap:disabled { opacity:.5; cursor:default; }
  .cam-bar { position:absolute; left:0; right:0; bottom:0; z-index:4;
             display:flex; align-items:baseline; gap:10px; padding:10px 12px;
             background:linear-gradient(to top, rgba(0,0,0,.7), transparent); }
  .cam-name { font-size:13px; color:#fff; }
  .cam-who { font-weight:500; font-size:14px; color:#d9d9d9; margin-left:auto; }
  .cam-who.known { color:#81c784; }
  .cam-who.unknown { color:#ef9a9a; }
  .empty-cams { grid-column:1/-1; padding:32px; text-align:center; color:var(--secondary);
                font-size:14px; background:var(--card); box-shadow:var(--shadow);
                border:1px solid var(--card-border); border-radius:var(--r); }

  /* Desktop: live preview on the left, controls stacked to its right.
     Narrow screens collapse to one column with the preview on top. */
  .layout { display:grid; gap:16px; align-items:start;
            grid-template-columns:minmax(0,1.15fr) minmax(0,1fr); }
  .panel { display:grid; gap:16px; align-content:start; }
  @media (min-width:861px) { .cams { position:sticky; top:16px; } }
  @media (max-width:860px) { .layout { grid-template-columns:1fr; } }

  .card { background:var(--card); border:1px solid var(--card-border);
          border-radius:var(--r); box-shadow:var(--shadow); padding:16px; }
  .card > h2 { margin:0 0 2px; font-size:16px; font-weight:500; color:var(--text); }
  .card .lead { margin:0 0 14px; font-size:13px; color:var(--secondary); }

  .field { display:flex; flex-direction:column; gap:6px; }
  label.lbl { font-size:12px; color:var(--secondary); }
  input[type=text] { font:inherit; padding:10px 12px; border-radius:8px;
                     background:var(--field); color:var(--text);
                     border:1px solid var(--divider); width:100%; }
  input[type=text]:focus-visible { outline:none; border-color:var(--primary);
                     box-shadow:0 0 0 1px var(--primary); }
  .btns { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
  button { font:inherit; font-weight:500; padding:9px 16px; border-radius:8px;
           border:1px solid transparent; cursor:pointer; }
  button:focus-visible { outline:2px solid var(--primary); outline-offset:2px; }
  .btn-primary { background:var(--primary); color:#fff; }
  .btn-primary:hover { filter:brightness(1.06); }
  .btn-ghost { background:transparent; color:var(--primary); border-color:var(--divider); }
  .btn-ghost:hover { background:var(--primary-soft); }
  button:disabled { opacity:.5; cursor:default; filter:none; }
  .msg { margin-top:11px; font-size:13px; min-height:1.25em; color:var(--secondary); }
  .msg.ok { color:var(--success); } .msg.err { color:var(--error); }

  .review { display:none; gap:13px; align-items:flex-start; margin-top:4px; }
  .review.show { display:flex; }
  .review img { width:76px; height:76px; border-radius:8px; object-fit:cover;
                border:2px solid var(--primary); flex:none; }
  .review .rc { flex:1; min-width:0; }

  ul.list { list-style:none; padding:0; margin:14px 0 0; }
  ul.list .empty { color:var(--secondary); font-size:13px; padding:6px 0; }
  .item { display:flex; align-items:center; gap:12px; padding:10px 0;
          border-top:1px solid var(--divider); }
  .item:first-child { border-top:0; }
  .thumb { width:42px; height:42px; border-radius:8px; object-fit:cover; flex:none;
           background:var(--field); border:1px solid var(--divider); }
  .thumb.unknown { border-color:var(--error); }
  .col { flex:1; min-width:0; }
  .col .name { font-weight:500; font-size:14px; }
  .col .name.is-unknown { color:var(--error); }
  .col .meta { font-size:12px; color:var(--secondary); }
  .badge { font-size:11px; font-weight:500; padding:3px 9px; border-radius:999px; }
  .badge.known { color:#fff; background:var(--success); }
  .badge.unknown { color:#fff; background:var(--error); }
  .link { background:none; border:0; padding:6px 8px; color:var(--primary);
          font-size:13px; font-weight:500; cursor:pointer; }
  .link:hover { text-decoration:underline; }
  .link.danger { color:var(--error); }
  /* Sightings: a row is a button to blow the face up and name it */
  .item.click { cursor:pointer; border-radius:8px;
                transition:background .15s; }
  .item.click:hover { background:var(--primary-soft); }

  /* Lightbox: big face + name field underneath */
  .modal { position:fixed; inset:0; z-index:50; display:flex;
           align-items:center; justify-content:center; padding:16px;
           background:rgba(0,0,0,.6); }
  .modal[hidden] { display:none; }
  .modal-card { position:relative; width:100%; max-width:340px;
                background:var(--card); border:1px solid var(--card-border);
                border-radius:var(--r); box-shadow:var(--shadow); padding:20px; }
  .modal-x { position:absolute; top:8px; right:8px; width:32px; height:32px;
             font-size:20px; line-height:1; padding:0; border-radius:8px;
             background:transparent; color:var(--secondary); border:0; cursor:pointer; }
  .modal-x:hover { background:var(--field); color:var(--text); }
  .modal-img { display:block; width:100%; max-width:280px; margin:0 auto 14px;
               aspect-ratio:1/1; object-fit:cover; border-radius:12px;
               border:2px solid var(--primary); background:var(--field); }
  .modal-img.unknown { border-color:var(--error); }
  .modal-meta { text-align:center; font-size:13px; color:var(--secondary);
                margin-bottom:16px; }
  .modal .btns { margin-top:14px; }
  .modal .btns button { flex:1; text-align:center; }

  @keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:.35;} }
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

  <div class="layout">

    <div class="cams" id="cams">
      <div class="empty-cams" id="emptyCams" style="display:none">
        No cameras configured. Add one on the Configuration tab, then restart.
      </div>
    </div>

    <div class="panel">

      <section class="card enroll">
        <h2>Enroll a face</h2>
        <p class="lead">Press <b>Capture</b> on a camera, or upload a clear photo,
           then give it a name. A few angles per person works best.</p>

        <div class="field">
          <label class="lbl" for="name">Name</label>
          <input type="text" id="name" list="names" placeholder="e.g. Alex" autocomplete="off">
        </div>

        <div class="btns" id="captureBtns">
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
        <p class="lead">Every recognized and unknown face, with its camera. Click a
           sighting to enlarge it and put a name to the face - naming more shots of
           the same person sharpens their recognition.</p>
        <ul class="list" id="log"></ul>
      </section>

    </div>
  </div>
</div>

<datalist id="names"></datalist>

<div class="modal" id="modal" hidden>
  <div class="modal-card">
    <button class="modal-x" id="modalX" aria-label="Close">&times;</button>
    <img class="modal-img" id="modalImg" alt="Sighting face">
    <div class="modal-meta" id="modalMeta"></div>
    <div class="field">
      <label class="lbl" for="modalName">Name this face</label>
      <input type="text" id="modalName" list="names" placeholder="Type or pick a name" autocomplete="off">
    </div>
    <div class="btns">
      <button class="btn-primary" id="modalSave">Save</button>
      <button class="btn-ghost" id="modalCancel">Cancel</button>
    </div>
    <div class="msg" id="modalMsg" aria-live="polite">&nbsp;</div>
  </div>
</div>

<script>
(function(){
  var pendingToken = null, aspectMode = "auto";
  var tiles = {};   // slug -> { root, img, who }

  function el(id){ return document.getElementById(id); }
  function setMsg(t, kind){ var m=el("msg"); m.textContent=t||" ";
    m.className="msg"+(kind?(" "+kind):""); }
  function fmtTime(t){ return t ? new Date(t*1000).toLocaleString() : "-"; }
  function pct(s){ return Math.round(s*100)+"%"; }
  function api(path, opts){
    return fetch(path, Object.assign({cache:"no-store"}, opts||{}))
      .then(function(r){ return r.json(); });
  }

  // ---- camera tiles + polled feeds ----
  function ensureTile(cam){
    if(tiles[cam.slug]) return tiles[cam.slug];
    var root=document.createElement("div"); root.className="cam";
    var img=document.createElement("img"); img.alt=cam.name+" live view"; root.appendChild(img);
    var cap=document.createElement("button"); cap.className="cap"; cap.textContent="Capture";
    cap.addEventListener("click", function(){ captureFrom(cam.slug, cap); });
    root.appendChild(cap);
    var bar=document.createElement("div"); bar.className="cam-bar";
    var nm=document.createElement("span"); nm.className="cam-name"; nm.textContent=cam.name;
    var who=document.createElement("span"); who.className="cam-who";
    bar.appendChild(nm); bar.appendChild(who); root.appendChild(bar);
    el("cams").appendChild(root);
    var t={ root:root, img:img, who:who }; tiles[cam.slug]=t;
    pollTile(cam.slug);
    return t;
  }
  function pollTile(slug){
    var t=tiles[slug]; if(!t) return;
    var probe=new Image();
    probe.onload=function(){
      if(aspectMode==="auto" && probe.naturalWidth && probe.naturalHeight){
        t.root.style.aspectRatio=probe.naturalWidth+" / "+probe.naturalHeight;
      }
      t.img.src=probe.src;
    };
    probe.src="preview.jpg?cam="+encodeURIComponent(slug)+"&t="+Date.now();
  }
  function refreshFeeds(){ for(var slug in tiles){ pollTile(slug); } }

  function captureFrom(slug, btn){
    btn.disabled=true; setMsg("Looking for a face...");
    api("enroll/capture?cam="+encodeURIComponent(slug), {method:"POST"}).then(function(r){
      btn.disabled=false;
      if(r.ok && r.token){ setMsg(r.message, "ok"); showReview(r.thumb, r.token); }
      else { setMsg(r.message || "No face found.", "err"); }
    }).catch(function(){ btn.disabled=false; setMsg("Something went wrong. Try again.","err"); });
  }

  function refreshStatus(){
    api("status").then(function(s){
      if(s.aspect) aspectMode=s.aspect;
      var cams=s.cameras||[];
      el("emptyCams").style.display = cams.length ? "none" : "";
      var anyOk=false, anyKnown=false, anyUnknown=false;
      cams.forEach(function(c){
        var t=ensureTile(c);
        if(aspectMode!=="auto") t.root.style.aspectRatio=aspectMode.replace(":"," / ");
        t.root.classList.toggle("known", c.state==="known");
        t.root.classList.toggle("unknown", c.state==="unknown");
        t.root.classList.toggle("offline", !c.camera_ok);
        if(c.state==="known" && c.recognized) t.who.textContent=c.recognized+"  "+pct(c.score);
        else if(c.state==="unknown") t.who.textContent="Unknown";
        else if(c.camera_ok) t.who.textContent=c.faces+(c.faces===1?" face":" faces");
        else t.who.textContent="no signal";
        t.who.className="cam-who"+(c.state==="known"?" known":(c.state==="unknown"?" unknown":""));
        anyOk=anyOk||c.camera_ok; anyKnown=anyKnown||c.state==="known"; anyUnknown=anyUnknown||c.state==="unknown";
      });
      var pill=el("pill");
      pill.className="pill"+(anyUnknown?" alert":(anyOk?" live":""));
      el("pillText").textContent = cams.length ? (anyOk?"Live":"No signal") : "Set up cameras";
    }).catch(function(){});
  }

  // ---- known people ----
  function makeThumb(b64, unknown){
    if(b64){ var im=document.createElement("img"); im.className="thumb"+(unknown?" unknown":"");
      im.src="data:image/jpeg;base64,"+b64; im.alt=""; return im; }
    var sp=document.createElement("span"); sp.className="thumb"+(unknown?" unknown":""); return sp;
  }
  function setNameOptions(names){
    var dl=el("names"); dl.innerHTML="";
    names.forEach(function(n){
      var o=document.createElement("option"); o.value=n; dl.appendChild(o);
    });
  }
  function refreshPeople(){
    api("people").then(function(d){
      var ul=el("people"); ul.innerHTML="";
      setNameOptions((d.people||[]).map(function(p){ return p.name; }));
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
            .then(function(r){ setMsg(r.message, r.ok?"ok":"err"); refreshPeople(); refreshLog(); });
        });
        li.appendChild(del); ul.appendChild(li);
      });
    }).catch(function(){});
  }

  // ---- sightings (camera-tagged; click a row to blow it up and name it) ----
  function refreshLog(){
    api("log").then(function(d){
      var ul=el("log"); ul.innerHTML="";
      if(!d.events.length){
        var li=document.createElement("li");
        li.className="empty"; li.textContent="No sightings yet.";
        ul.appendChild(li); return;
      }
      d.events.forEach(function(e){
        var li=document.createElement("li"); li.className="item click";
        li.title="Click to enlarge and name";
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
        meta.textContent=(e.camera?e.camera+" - ":"")+fmtTime(e.ts);
        col.appendChild(top); col.appendChild(meta); li.appendChild(col);
        li.addEventListener("click", function(){ openSighting(e); });
        ul.appendChild(li);
      });
    }).catch(function(){});
  }

  // ---- sighting lightbox: enlarge, then name (known names autocomplete) ----
  var modalEvent=null;
  function setModalMsg(t, kind){ var m=el("modalMsg"); m.textContent=t||" ";
    m.className="msg"+(kind?(" "+kind):""); }
  function openSighting(e){
    modalEvent=e;
    var img=el("modalImg");
    img.src=e.thumb?("data:image/jpeg;base64,"+e.thumb):"";
    img.className="modal-img"+(e.unknown?" unknown":"");
    el("modalMeta").textContent=
      (e.unknown?"Unknown":(e.name+"  "+pct(e.score)))
      +"  -  "+(e.camera?e.camera+" - ":"")+fmtTime(e.ts);
    var input=el("modalName");
    input.value=e.unknown?"":(e.name||"");
    setModalMsg(""); el("modalSave").disabled=false;
    el("modal").hidden=false; input.focus();
  }
  function closeModal(){ el("modal").hidden=true; modalEvent=null; }
  function saveSighting(){
    if(!modalEvent) return;
    var n=el("modalName").value.trim();
    if(!n){ setModalMsg("Enter a name for this face.","err"); el("modalName").focus(); return; }
    el("modalSave").disabled=true;
    api("sighting/name?id="+encodeURIComponent(modalEvent.id)+"&name="+encodeURIComponent(n),
        {method:"POST"}).then(function(r){
      if(r.ok){ setMsg(r.message,"ok"); closeModal(); refreshPeople(); refreshLog(); }
      else { setModalMsg(r.message||"Could not save.","err"); el("modalSave").disabled=false; }
    }).catch(function(){ setModalMsg("Save failed. Try again.","err"); el("modalSave").disabled=false; });
  }
  el("modalSave").addEventListener("click", saveSighting);
  el("modalCancel").addEventListener("click", closeModal);
  el("modalX").addEventListener("click", closeModal);
  el("modal").addEventListener("click", function(ev){ if(ev.target===el("modal")) closeModal(); });
  el("modalName").addEventListener("keydown", function(ev){ if(ev.key==="Enter") saveSighting(); });
  document.addEventListener("keydown", function(ev){
    if(ev.key==="Escape" && !el("modal").hidden) closeModal(); });

  // ---- enrollment: capture (per camera) / upload -> review -> save ----
  function showReview(thumbB64, token){
    pendingToken=token;
    el("reviewThumb").src="data:image/jpeg;base64,"+thumbB64;
    el("review").classList.add("show");
    el("name").focus();
  }
  function resetEnroll(){
    pendingToken=null;
    el("review").classList.remove("show");
  }
  el("pick").addEventListener("click", function(){ el("file").click(); });
  el("file").addEventListener("change", function(){
    var f=this.files[0]; if(!f) return;
    el("pick").disabled=true; setMsg("Looking for a face...");
    api("enroll/upload", {method:"POST", body:f}).then(function(r){
      el("pick").disabled=false;
      if(r.ok && r.token){ setMsg(r.message,"ok"); showReview(r.thumb, r.token); }
      else { setMsg(r.message,"err"); }
    }).catch(function(){ el("pick").disabled=false; setMsg("Something went wrong. Try again.","err"); });
    this.value="";
  });
  el("save").addEventListener("click", function(){
    var n=el("name").value.trim();
    if(!n){ setMsg("Enter a name first.","err"); el("name").focus(); return; }
    if(!pendingToken){ resetEnroll(); return; }
    busy(true);
    api("enroll/commit?token="+encodeURIComponent(pendingToken)+"&name="+encodeURIComponent(n),
        {method:"POST"}).then(function(r){
      busy(false); setMsg(r.message, r.ok?"ok":"err");
      if(r.ok){ el("name").value=""; resetEnroll(); refreshPeople(); refreshLog(); }
    }).catch(function(){ busy(false); setMsg("Save failed. Try again.","err"); });
  });
  el("retake").addEventListener("click", function(){
    if(pendingToken){ api("enroll/cancel?token="+encodeURIComponent(pendingToken), {method:"POST"}); }
    resetEnroll(); setMsg("");
  });
  function busy(on){ el("save").disabled=on; el("retake").disabled=on; }

  refreshStatus(); refreshPeople(); refreshLog();
  setInterval(refreshStatus, 1500);
  setInterval(refreshFeeds, 600);
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

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/enroll/capture":
                self._json(app.stage_from_frame(self._param("cam")))
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
            elif path == "/preview.jpg":
                jpeg = app.preview_jpeg(self._param("cam"))
                if jpeg:
                    self._send(200, "image/jpeg", jpeg)
                else:
                    self._send(503, "text/plain", b"no frame yet")
            else:
                self._send(404, "text/plain", b"not found")

        do_HEAD = do_GET

    return ThreadingHTTPServer((host, port), Handler)
