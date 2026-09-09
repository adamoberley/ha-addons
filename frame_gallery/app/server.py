"""Ingress control panel: the current piece, its details, and quick actions.

Bound to 0.0.0.0 for ingress (HA authenticates it). URLs are relative so they
work under the ingress token path.
  - `trigger` is set by "Show next" to request a fresh pick.
  - `repush` is set by "Re-push to TV" to re-send the current image.
  - `on_url` validates+queues a pasted reframed.gallery link ("Show this").
  - `on_hide` hides the current piece for good and picks another right away;
    `on_unhide` clears that list.
  - `status` is a dict the loop updates and the panel reads.

Endpoints: GET / (panel), /status (JSON), /preview.jpg, /healthz;
POST /next, /repush, /show, /hide, /unhide.
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("frame-gallery.server")

PREVIEW_PATH = "/data/last.jpg"

CONTROL_HTML = b"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>REFRAMED Gallery</title>
<link rel="icon" id="favicon">
<style>
  :root {
    color-scheme: light dark;
    --primary:#03a9f4; --accent:#03a9f4; --bg:#f5f5f5; --card:#ffffff; --text:#212121;
    --secondary:#727272; --divider:rgba(0,0,0,.12); --screen:#15161a;
    --chip:rgba(0,0,0,.06);
    --shadow:0 2px 1px -1px rgba(0,0,0,.2),0 1px 1px 0 rgba(0,0,0,.14),0 1px 3px 0 rgba(0,0,0,.12);
    --card-border:transparent;
    --ok:#2e7d32; --busy:#0277bd; --err:#c62828; --wait:#9e9e9e;
    --sans:Roboto,"Helvetica Neue",-apple-system,system-ui,"Segoe UI",Arial,sans-serif;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#111111; --card:#1c1c1c; --text:#e1e1e1; --secondary:#9b9b9b;
            --divider:rgba(225,225,225,.12); --chip:rgba(225,225,225,.08);
            --shadow:none; --card-border:rgba(225,225,225,.12);
            --ok:#81c784; --busy:#4fc3f7; --err:#ef9a9a; --wait:#9e9e9e; }
  }
  * { box-sizing:border-box; }
  body { font-family:var(--sans); margin:0; padding:16px; background:var(--bg);
         color:var(--text); line-height:1.5; -webkit-font-smoothing:antialiased; }
  .card { max-width:820px; margin:0 auto; background:var(--card); border-radius:14px;
          box-shadow:var(--shadow); border:1px solid var(--card-border); overflow:hidden; }
  .accent { height:4px; background:var(--accent); transition:background .6s ease; }
  .body { padding:20px; }
  .head { display:flex; align-items:baseline; justify-content:space-between; gap:12px;
          flex-wrap:wrap; margin-bottom:14px; }
  h1 { font-size:1.25rem; font-weight:500; margin:0; }
  .head .sched { color:var(--secondary); font-size:.82rem; white-space:nowrap; }
  .frame { border-radius:10px; overflow:hidden; background:var(--screen);
           aspect-ratio:16/9; display:grid; place-items:center; }
  .frame img { width:100%; height:100%; object-fit:contain; display:block; }
  .frame .empty { color:#888; font-size:.9rem; }
  .caption { margin:16px 2px 4px; }
  .title { font-size:1.18rem; font-weight:500; }
  .byline { font-size:.98rem; margin-top:2px; }
  .meta2 { color:var(--secondary); font-size:.88rem; margin-top:3px; }
  .credit { color:var(--secondary); font-size:.78rem; margin-top:6px; opacity:.85; }
  a.wiki { color:inherit; text-decoration:none; border-bottom:1px dotted transparent; }
  a.wiki:hover { border-bottom-color:currentColor; }
  .statusrow { display:flex; align-items:center; gap:8px; flex-wrap:wrap;
               margin:16px 2px 0; font-size:.86rem; color:var(--secondary); }
  .pill { display:inline-flex; align-items:center; gap:7px; padding:4px 11px;
          border-radius:999px; background:var(--chip); color:var(--text); font-weight:500; }
  .dot { width:8px; height:8px; border-radius:50%; background:var(--wait); }
  .pill.ok .dot{background:var(--ok)}
  .pill.busy .dot{background:var(--busy);animation:pulse 1s infinite}
  .pill.err .dot{background:var(--err)} .pill.err{color:var(--err)}
  .wait-msg{color:var(--secondary)}
  @keyframes pulse{50%{opacity:.35}}
  .sep { opacity:.5; }
  .chips { display:flex; gap:6px; flex-wrap:wrap; margin:12px 2px 0; }
  .chip { font-size:.74rem; padding:3px 9px; border-radius:999px; background:var(--chip);
          color:var(--secondary); }
  .actions { display:flex; gap:10px; flex-wrap:wrap; margin-top:18px; }
  button { font:inherit; font-weight:500; padding:10px 18px; border:0; border-radius:9px;
           cursor:pointer; }
  button.primary { background:var(--primary); color:#fff; }
  button.ghost { background:var(--chip); color:var(--text); }
  button:hover { filter:brightness(1.06); }
  button:disabled { opacity:.5; cursor:default; filter:none; }
  .hiddenrow { display:flex; align-items:center; gap:8px; margin-top:10px;
               font-size:13px; color:var(--secondary); }
  .hiddenrow[hidden] { display:none; }
  button.linkbtn { background:none; padding:0; color:var(--primary);
                   font-size:13px; font-weight:500; }
  button.linkbtn:hover { text-decoration:underline; filter:none; }
  .link { margin-top:18px; padding-top:16px; border-top:1px solid var(--divider); }
  .link label { display:block; font-size:.86rem; font-weight:500; margin-bottom:2px; }
  .link .hint { color:var(--secondary); font-size:.78rem; margin-bottom:9px; }
  .linkrow { display:flex; gap:10px; flex-wrap:wrap; }
  .linkrow input { flex:1 1 260px; min-width:0; font:inherit; font-size:.92rem;
                   padding:10px 12px; border-radius:9px; color:var(--text);
                   background:var(--bg); border:1px solid var(--divider); }
  .linkrow input:focus { outline:2px solid var(--primary); outline-offset:-1px; }
  .msg { font-size:.8rem; margin-top:8px; min-height:1.1em; color:var(--secondary); }
  .msg.bad { color:var(--err); }
</style></head><body>
<div class="card">
  <div class="accent" id="accent"></div>
  <div class="body">
    <div class="head">
      <h1>REFRAMED Gallery</h1>
      <span class="sched" id="sched"></span>
    </div>
    <div class="frame"><span class="empty" id="empty">Nothing shown yet</span>
         <img id="prev" alt="" hidden crossorigin="anonymous"></div>
    <div class="caption" id="caption"></div>
    <div class="statusrow">
      <span class="pill wait" id="pill"><span class="dot"></span>
        <span id="pilltext">Starting</span></span>
      <span class="sep">&middot;</span><span id="tvs">-</span>
      <span class="sep">&middot;</span><span id="changed">never</span>
    </div>
    <div class="chips" id="chips"></div>
    <div class="actions">
      <button class="primary" id="go">Show next</button>
      <button class="ghost" id="repush">Re-push to TV</button>
      <button class="ghost" id="hide" title="Hide this piece and show another">
        Never show this</button>
    </div>
    <div class="hiddenrow" id="hiddenrow" hidden>
      <span id="hiddentext"></span>
      <button class="linkbtn" id="unhide">Un-hide all</button>
    </div>
    <div class="link">
      <label for="url">Show a specific piece</label>
      <div class="hint">Paste a reframed.gallery artwork link &mdash; it goes up now,
        whatever the collection says.</div>
      <form class="linkrow" id="linkform">
        <input id="url" name="url" type="text" autocomplete="off" spellcheck="false"
               placeholder="https://www.reframed.gallery/artist/artwork">
        <button class="ghost" id="show" type="submit">Show this</button>
      </form>
      <div class="msg" id="msg"></div>
    </div>
  </div>
</div>
<script>
  var lastTs = 0;
  var SEP = ' <span class="sep">&middot;</span> ';
  function esc(s){
    var d=document.createElement('div'); d.textContent=(s==null?'':s); return d.innerHTML;
  }
  function wiki(text, query){
    if(!text) return '';
    var u='https://en.wikipedia.org/wiki/Special:Search?search='+encodeURIComponent(query||text);
    return '<a class="wiki" href="'+u+'" target="_blank" rel="noopener">'+esc(text)+'</a>';
  }
  function yearLink(y){
    if(!y) return '';
    var m=(''+y).match(/\\d{4}/);
    return wiki(y, m ? (m[0]+' in art') : y);
  }
  function rel(t){
    if(!t) return 'never';
    var s=Math.max(0, Math.floor(Date.now()/1000 - t));
    if(s<45) return 'just now';
    if(s<5400) return Math.max(1,Math.round(s/60))+' min ago';
    if(s<86400) return Math.round(s/3600)+' hr ago';
    return Math.round(s/86400)+' d ago';
  }
  function tintFavicon(img){
    try{
      var c=document.createElement('canvas'); c.width=c.height=16;
      var x=c.getContext('2d'); x.drawImage(img,0,0,16,16);
      var d=x.getImageData(0,0,16,16).data, r=0,g=0,b=0,n=0;
      for(var i=0;i<d.length;i+=4){ r+=d[i]; g+=d[i+1]; b+=d[i+2]; n++; }
      r=Math.round(r/n); g=Math.round(g/n); b=Math.round(b/n);
      var col='rgb('+r+','+g+','+b+')';
      document.documentElement.style.setProperty('--accent', col);
      var f=document.createElement('canvas'); f.width=f.height=32;
      var fx=f.getContext('2d'); fx.fillStyle=col;
      fx.beginPath(); fx.moveTo(7,0);
      fx.arcTo(32,0,32,32,7); fx.arcTo(32,32,0,32,7);
      fx.arcTo(0,32,0,0,7); fx.arcTo(0,0,32,0,7); fx.closePath(); fx.fill();
      document.getElementById('favicon').href=f.toDataURL('image/png');
    }catch(e){}
  }
  function render(s){
    document.getElementById('sched').textContent = s.daily_time
      ? 'Switches daily at '+s.daily_time
      : 'Switches every '+s.interval_minutes+' min';

    var cap='';
    if(s.title){
      var q=((s.title||'')+' '+(s.artist||'')).trim();
      cap += '<div class="title">'+wiki(s.title, q)+'</div>';
      var by=[];
      if(s.artist) by.push(wiki(s.artist, s.artist));
      if(s.year) by.push(yearLink(s.year));
      if(by.length) cap += '<div class="byline">'+by.join(SEP)+'</div>';
      var m=[];
      if(s.medium) m.push(esc(s.medium));
      if(s.movement) m.push(esc(s.movement));
      if(m.length) cap += '<div class="meta2">'+m.join(SEP)+'</div>';
      if(s.credit) cap += '<div class="credit">Source: '+esc(s.credit)+'</div>';
    } else {
      cap = '<div class="byline wait-msg">Waiting for the first piece&hellip;</div>';
    }
    document.getElementById('caption').innerHTML = cap;

    var pill=document.getElementById('pill'), pt=document.getElementById('pilltext'), cls, txt;
    var noTv=(s.last_ts && s.tv_count && s.tv_ok===0);
    if(s.busy){ cls='busy'; txt='Fetching a new piece'; }
    else if(s.last_error){ cls='err'; txt=s.last_error; }
    else if(noTv){ cls='err'; txt='No TVs reached'; }
    else if(s.last_ts){ cls='ok'; txt=s.note ? s.note : 'Idle'; }
    else { cls='wait'; txt='Starting'; }
    pill.className='pill '+cls; pt.textContent=txt;

    var ok=(s.tv_ok==null?'-':s.tv_ok), tot=(s.tv_count==null?'-':s.tv_count);
    document.getElementById('tvs').textContent = ok+'/'+tot+' TV'+(tot===1?'':'s')+' reached';
    document.getElementById('changed').textContent = 'changed '+rel(s.last_ts);

    var chips='';
    if(s.link) chips += '<span class="chip">Your link</span>';
    if(s.collection) chips += '<span class="chip">Collection: '+esc(s.collection)+'</span>';
    if(s.matte && s.matte!=='none') chips += '<span class="chip">Matte: '+esc(s.matte)+'</span>';
    if(s.library_size > 1) chips += '<span class="chip">Keeps '+esc(s.library_size)+' on TV</span>';
    if(s.source) chips += '<span class="chip">'+esc(s.source)+'</span>';
    document.getElementById('chips').innerHTML = chips;

    document.getElementById('go').disabled = !!s.busy;
    document.getElementById('repush').disabled = !!s.busy || !s.last_ts;
    document.getElementById('hide').disabled = !!s.busy || !s.key;

    var n = s.hidden_count || 0;
    document.getElementById('hiddenrow').hidden = !n;
    document.getElementById('hiddentext').textContent =
      n + (n === 1 ? ' piece hidden' : ' pieces hidden');

    if(s.last_ts && s.last_ts !== lastTs){
      lastTs = s.last_ts;
      var img=document.getElementById('prev');
      img.onload=function(){ tintFavicon(img); };
      img.src='preview.jpg?t='+s.last_ts; img.hidden=false;
      document.getElementById('empty').style.display='none';
      setMsg('', false);          // the new caption is the answer now
    }
  }
  function setMsg(text, bad){
    var m=document.getElementById('msg');
    m.textContent=text; m.className='msg'+(bad?' bad':'');
  }
  function refresh(){
    fetch('status',{cache:'no-store'})
      .then(function(r){return r.json();}).then(render).catch(function(){});
  }
  function post(url, btn){
    var b=document.getElementById(btn); b.disabled=true;
    fetch(url,{method:'POST'}).catch(function(){});
    setTimeout(refresh, 600);
  }
  document.getElementById('go').onclick=function(){ post('next','go'); };
  document.getElementById('repush').onclick=function(){ post('repush','repush'); };
  function act(url, btn){
    var b=document.getElementById(btn); b.disabled=true; setMsg('', false);
    fetch(url,{method:'POST'})
      .then(function(r){ return r.json(); })
      .then(function(d){ setMsg(d.message||'', !d.ok); })
      .catch(function(){ setMsg('Could not reach the app', true); })
      .then(function(){ setTimeout(refresh, 600); });
  }
  document.getElementById('hide').onclick=function(){ act('hide','hide'); };
  document.getElementById('unhide').onclick=function(){ act('unhide','unhide'); };
  document.getElementById('linkform').onsubmit=function(ev){
    ev.preventDefault();
    var inp=document.getElementById('url'), btn=document.getElementById('show');
    var url=inp.value.trim();
    if(!url){ inp.focus(); return; }
    btn.disabled=true; setMsg('', false);
    fetch('show',{method:'POST',
                  headers:{'Content-Type':'application/x-www-form-urlencoded'},
                  body:'url='+encodeURIComponent(url)})
      .then(function(r){ return r.json(); })
      .then(function(d){
        setMsg(d.message||'', !d.accepted);
        if(d.accepted){ inp.value=''; }
      })
      .catch(function(){ setMsg('Could not reach the app', true); })
      .then(function(){ btn.disabled=false; setTimeout(refresh, 600); });
  };
  refresh(); setInterval(refresh, 2000);
</script></body></html>"""


MAX_BODY = 4096          # a URL, not an upload endpoint


def make_server(trigger: threading.Event, status: dict,
                repush: threading.Event | None = None,
                wake: threading.Event | None = None,
                on_url=None, on_hide=None, on_unhide=None,
                host: str = "0.0.0.0", port: int = 8099):
    debug = status.get("_debug", False)

    def _signal(event):
        if event is not None:
            event.set()
        if wake is not None:
            wake.set()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if debug:
                log.debug("%s - %s", self.address_string(), fmt % args)

        def _send(self, code, ctype, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _body_field(self, name: str) -> str:
            """One field from a form-encoded (or JSON) POST body."""
            try:
                length = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
            except ValueError:
                return ""
            if length <= 0:
                return ""
            raw = self.rfile.read(length).decode("utf-8", "replace")
            if raw.lstrip().startswith("{"):
                try:
                    return str(json.loads(raw).get(name, ""))
                except (ValueError, AttributeError):
                    return ""
            return (parse_qs(raw).get(name) or [""])[0]

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/next":
                _signal(trigger)
                log.info("manual 'show next' requested from control panel")
                self._send(200, "application/json", b'{"queued":true}')
            elif path == "/repush":
                _signal(repush)
                log.info("manual 're-push' requested from control panel")
                self._send(200, "application/json", b'{"queued":true}')
            elif path in ("/hide", "/unhide"):
                action = on_hide if path == "/hide" else on_unhide
                if action is None:
                    ok, message = False, "not available"
                else:
                    ok, message = action()
                self._send(200 if ok else 400, "application/json",
                           json.dumps({"ok": ok, "message": message}).encode())
            elif path == "/show":
                url = self._body_field("url").strip()
                if on_url is None:
                    accepted, message = False, "showing links isn't available"
                else:
                    accepted, message = on_url(url)
                log.info("link %s from control panel: %s",
                         "accepted" if accepted else "rejected", url or "(empty)")
                self._send(200 if accepted else 400, "application/json",
                           json.dumps({"accepted": accepted, "message": message}).encode())
            else:
                self._send(404, "text/plain", b"not found")

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", ""):
                self._send(200, "text/html; charset=utf-8", CONTROL_HTML)
            elif path == "/status":
                public = {k: v for k, v in status.items() if not k.startswith("_")}
                self._send(200, "application/json", json.dumps(public).encode())
            elif path == "/healthz":
                err = status.get("last_error")
                last_ts = status.get("last_ts")
                tv_count = status.get("tv_count", 0)
                tv_ok = status.get("tv_ok", 0)
                # Degraded only on a real failure: a hard error, or a completed
                # cycle that reached zero TVs. A partial push (tv_ok>0) is healthy.
                if err or (last_ts and tv_count and tv_ok == 0):
                    state, code = "degraded", 503
                elif last_ts:
                    state, code = "ok", 200
                else:
                    state, code = "starting", 200
                body = json.dumps({
                    "status": state, "busy": status.get("busy", False),
                    "last_ts": last_ts or 0, "last_error": err, "note": status.get("note"),
                    "tv_ok": tv_ok, "tv_count": tv_count,
                }).encode()
                self._send(code, "application/json", body)
            elif path == "/preview.jpg":
                try:
                    with open(PREVIEW_PATH, "rb") as fh:
                        self._send(200, "image/jpeg", fh.read())
                except OSError:
                    self._send(404, "text/plain", b"no preview yet")
            else:
                self._send(404, "text/plain", b"not found")

        do_HEAD = do_GET

    return ThreadingHTTPServer((host, port), Handler)
