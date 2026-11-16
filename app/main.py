from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from . import collector, db, rules, worker
from . import schedule as sched
from .i18n import _, set_lang
from .version import VERSION

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("disk-monitor")
STATIC = os.path.join(os.path.dirname(__file__), "static")
APP_USER = os.environ.get("APP_USER", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
# sin contraseña la web queda abierta: sólo se permite si se pide explícitamente (AUTH_DISABLED=1)
AUTH_DISABLED = not APP_PASSWORD and os.environ.get("AUTH_DISABLED", "").lower() in ("1", "true", "yes")
NO_PASSWORD_MSG = {"es": ("Falta APP_PASSWORD en el archivo .env. Define una contraseña y aplica con "
                          "'docker compose up -d' (o AUTH_DISABLED=1 para usarlo sin contraseña, no recomendado)."),
                   "en": ("APP_PASSWORD is missing in the .env file. Set a password and apply it with "
                          "'docker compose up -d' (or AUTH_DISABLED=1 to run without a password, not recommended).")}
SECRET_FIELDS = {("telegram", "bot_token"), ("email", "password")}
MASK = "••••••••"


@asynccontextmanager
async def lifespan(app):
    db.init()
    task = asyncio.create_task(worker.loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

# ---------------- autenticación: cookie de sesión firmada (+ Basic Auth para scripts) ----------------
SESSION_COOKIE = "dm_session"
PUBLIC_PATHS = {"/health", "/login", "/api/login", "/favicon.svg", "/i18n.js"}
_fails: dict[str, list[float]] = {}


def _key() -> bytes:
    sec = db.get_state("session_secret")
    if not sec:
        sec = secrets.token_hex(32)
        db.set_state("session_secret", sec)
    return (sec + APP_PASSWORD).encode()


def _sign(user: str, exp: int) -> str:
    payload = f"{user}|{exp}"
    sig = hmac.new(_key(), payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def _valid_session(token: str | None) -> bool:
    if not token:
        return False
    try:
        user, exp, sig = base64.urlsafe_b64decode(token.encode()).decode().rsplit("|", 2)
    except Exception:  # noqa: BLE001
        return False
    good = hmac.new(_key(), f"{user}|{exp}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good) and int(exp) > time.time() and user == APP_USER


def _basic_ok(request: Request) -> bool:
    h = request.headers.get("authorization", "")
    if not h.lower().startswith("basic "):
        return False
    try:
        u, p = base64.b64decode(h[6:]).decode().split(":", 1)
    except Exception:  # noqa: BLE001
        return False
    return secrets.compare_digest(u, APP_USER) and secrets.compare_digest(p, APP_PASSWORD)


@app.middleware("http")
async def auth(request: Request, call_next):
    path = request.url.path
    lang = db.get_settings().get("language", "es")
    set_lang(lang)
    if not APP_PASSWORD and not AUTH_DISABLED and path not in ("/health", "/favicon.svg"):
        if path.startswith("/api/"):
            return JSONResponse({"detail": NO_PASSWORD_MSG[lang]}, status_code=503)
        return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>Disk Monitor</title>"
                            f"<p style='font:16px system-ui;max-width:560px;margin:15vh auto;padding:16px'>"
                            f"<b>{_('Disk Monitor no está configurado.')}</b><br><br>{NO_PASSWORD_MSG[lang]}</p>", status_code=503)
    if (AUTH_DISABLED or path in PUBLIC_PATHS
            or _valid_session(request.cookies.get(SESSION_COOKIE)) or _basic_ok(request)):
        return await call_next(request)
    if path.startswith("/api/"):
        return JSONResponse({"detail": _("no autenticado")}, status_code=401)
    return RedirectResponse("/login", status_code=303)


@app.get("/login")
async def login_page(request: Request):
    if AUTH_DISABLED or _valid_session(request.cookies.get(SESSION_COOKIE)):
        return RedirectResponse("/", status_code=303)
    return FileResponse(os.path.join(STATIC, "login.html"))


@app.post("/api/login")
async def login(request: Request, body: dict):
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 900]
    if len(recent) >= 10:
        raise HTTPException(429, _("demasiados intentos, espera unos minutos"))
    user, pw = str(body.get("username", "")), str(body.get("password", ""))
    if not (secrets.compare_digest(user, APP_USER) and secrets.compare_digest(pw, APP_PASSWORD)):
        _fails[ip] = recent + [now]
        log.warning("login fallido desde %s (usuario %r)", ip, user[:40])
        await asyncio.sleep(1)
        raise HTTPException(401, _("usuario o contraseña incorrectos"))
    _fails.pop(ip, None)
    max_age = 30 * 86400 if body.get("remember") else 12 * 3600
    resp = JSONResponse({"ok": True})
    resp.set_cookie(SESSION_COOKIE, _sign(user, int(now + max_age)), max_age=max_age if body.get("remember") else None,
                    httponly=True, samesite="lax", secure=request.headers.get("x-forwarded-proto") == "https")
    return resp


@app.post("/api/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


# ---------------- páginas ----------------

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-cache"})


@app.get("/i18n.js")
async def i18n_js():
    return FileResponse(os.path.join(STATIC, "i18n.js"), media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/favicon.svg")
async def favicon():
    return FileResponse(os.path.join(STATIC, "favicon.svg"), media_type="image/svg+xml")


@app.get("/health")
async def health():
    st = db.get_state("last_status", {}) or {}
    return {"ok": True, "version": VERSION, "last_check": st.get("ts"), "language": db.get_settings().get("language", "es")}


# ---------------- estado ----------------

def _strip(d: dict) -> dict:
    """Versión liviana de un disco para el panel (sin tabla de atributos ni logs completos)."""
    out = {k: v for k, v in d.items() if k not in ("attributes", "error_log", "messages")}
    st = dict(d.get("selftest") or {})
    st["last"] = next((x for x in st.get("log") or [] if x.get("passed") is not None), None)
    st.pop("log", None)
    out["selftest"] = st
    return out


@app.get("/api/status")
async def api_status():
    st = db.get_state("last_status", {}) or {}
    active = sorted(db.active_alerts().values(), key=lambda a: (-worker.SEV[a["severity"]], a["first_seen"]))
    since = int(time.time() - 86400)
    spark = {d["key"]: db.get_metrics(d["key"], "temp", since) for d in st.get("disks", [])}
    return {
        "ts": st.get("ts"), "duration": st.get("duration"), "server": st.get("server") or collector.host_name(),
        "disks": [_strip(d) for d in st.get("disks", [])], "pools": st.get("pools", []),
        "fs": st.get("fs", []), "missing": st.get("missing", []), "alerts": active, "spark": spark,
        "running": worker.status["running"], "next": worker.status["next"],
        "running_task": worker.status["running_task"],
        "last_error": worker.status["last_error"],
        "last_selftest_run": db.get_state("last_selftest_run"),
        "env": st.get("env") or {},
        "version": VERSION,
    }


@app.get("/api/disk/{key}")
async def api_disk(key: str, days: int = 7):
    st = db.get_state("last_status", {}) or {}
    d = next((x for x in st.get("disks", []) if x["key"] == key), None)
    if not d:
        raise HTTPException(404, _("disco no encontrado"))
    since = int(time.time() - min(days, 365) * 86400)
    hist = {n: db.get_metrics(key, n, since) for n in ("temp", "reallocated", "pending", "crc_errors", "percentage_used")}
    alerts = [a for a in db.list_alerts(500) if a["subject"] == key]
    return {"disk": d, "history": hist, "alerts": alerts[:50]}


@app.get("/api/history")
async def api_history(subject: str, name: str, days: int = 7):
    return db.get_metrics(subject, name, int(time.time() - min(days, 365) * 86400))


@app.post("/api/check")
async def api_check():
    if worker.status["running"]:
        raise HTTPException(409, _("ya hay una revisión en curso"))
    try:
        res = await worker.run_check("manual")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    worker.wake.set()
    return res


@app.post("/api/discover")
async def api_discover():
    """Detección de discos bajo demanda: re-escanea el hardware y hace una revisión completa."""
    if worker.status["running"]:
        raise HTTPException(409, _("ya hay una revisión en curso"))
    try:
        res = await worker.run_check("detección manual")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    worker.wake.set()
    return res


@app.get("/api/inventory")
async def api_inventory():
    st = db.get_state("last_status", {}) or {}
    present = {d["key"]: d for d in st.get("disks", [])}
    known = db.get_state("known_disks", {}) or {}
    out = []
    for k, v in known.items():
        d = present.get(k)
        out.append({"key": k, "model": v.get("model"), "serial": v.get("serial"), "dev": d["dev"] if d else v.get("dev"),
                    "name": d["name"] if d else None, "present": bool(d), "last_seen": v.get("last_seen"),
                    "state": d["state"] if d else "missing"})
    for k, d in present.items():
        if k not in known:
            out.append({"key": k, "model": d.get("model"), "serial": d.get("serial"), "dev": d["dev"], "name": d["name"],
                        "present": True, "last_seen": st.get("ts"), "state": d["state"]})
    return sorted(out, key=lambda x: (not x["present"], x.get("dev") or ""))


@app.post("/api/selftest")
async def api_selftest(body: dict):
    kind = body.get("type", "short")
    if kind not in ("short", "long", "conveyance"):
        raise HTTPException(400, _("tipo inválido"))
    keys = body.get("disks") or []
    res = await worker.run_selftests({"type": kind, "disks": keys})
    return {"results": res}


@app.get("/api/alerts")
async def api_alerts(limit: int = 300):
    return db.list_alerts(min(limit, 2000))


@app.post("/api/alerts/{aid}/ack")
async def api_ack(aid: int, body: dict):
    db.ack_alert(aid, bool(body.get("value", True)))
    return {"ok": True}


@app.get("/api/runs")
async def api_runs():
    return db.list_runs(100)


@app.get("/api/notifications")
async def api_notifications():
    return db.list_notifications(100)


@app.post("/api/disks/{key}/forget")
async def api_forget(key: str):
    known = db.get_state("known_disks", {}) or {}
    known.pop(key, None)
    db.set_state("known_disks", known)
    return {"ok": True}


# ---------------- configuración ----------------

def _masked(s: dict) -> dict:
    s = {k: (dict(v) if isinstance(v, dict) else v) for k, v in s.items()}
    for sec, f in SECRET_FIELDS:
        if s[sec].get(f):
            s[sec][f] = MASK
    return s


@app.get("/api/settings")
async def get_settings():
    return {"settings": _masked(db.get_settings()), "hostname": collector.host_name()}


@app.put("/api/settings")
async def put_settings(body: dict):
    cur = db.get_settings()
    for sec, f in SECRET_FIELDS:
        if isinstance(body.get(sec), dict) and body[sec].get(f) == MASK:
            body[sec][f] = cur[sec].get(f, "")
    if "tasks" in body:
        try:
            worker.validate_tasks(body["tasks"])
        except ValueError as e:
            raise HTTPException(400, str(e))
    if "language" in body and body["language"] not in ("es", "en"):
        raise HTTPException(400, _("idioma inválido"))
    s = db.save_settings(body)
    set_lang(s.get("language"))
    if body.get("language") and body["language"] != cur.get("language") and not worker.status["running"]:
        # nueva revisión para que las alertas activas queden redactadas en el idioma elegido
        asyncio.create_task(worker._safe(worker.run_check("cambio de idioma")))
    worker.wake.set()
    return {"settings": _masked(s)}


@app.get("/api/settings/export")
async def export_settings(include_secrets: int = 1):
    """Configuración para llevar a otro servidor (canales, umbrales, horarios).
    Se excluye lo propio de este equipo: nombre, URL y discos ignorados."""
    s = db.get_settings()
    for k in ("server_name", "base_url", "ignored_disks"):
        s.pop(k, None)
    for t in s.get("tasks") or []:
        t["targets"] = []          # discos y pools son propios de cada servidor
    if not include_secrets:
        for sec, f in SECRET_FIELDS:
            s[sec][f] = ""
    return JSONResponse({"disk_monitor_settings": 1, "settings": s},
                        headers={"Content-Disposition": 'attachment; filename="disk-monitor-config.json"'})


@app.post("/api/settings/import")
async def import_settings(body: dict):
    s = body.get("settings") if isinstance(body.get("settings"), dict) else None
    if not s or body.get("disk_monitor_settings") != 1:
        raise HTTPException(400, _("el archivo no es una exportación de Disk Monitor"))
    for k in ("server_name", "base_url", "ignored_disks"):
        s.pop(k, None)
    cur = db.get_settings()
    if "tasks" not in s and any(k in s for k in ("schedule", "selftests", "report")):
        s["tasks"] = db._migrate_tasks(s)      # exportación de la versión 1.0
    if "tasks" in s:
        try:
            worker.validate_tasks(s["tasks"])
        except ValueError as e:
            raise HTTPException(400, _("tareas inválidas: {e}", e=e))
    for sec, f in SECRET_FIELDS:   # si la exportación venía sin secretos, conservar los actuales
        if isinstance(s.get(sec), dict) and not s[sec].get(f):
            s[sec][f] = cur[sec].get(f, "")
    db.save_settings(s)
    worker.wake.set()
    return {"settings": _masked(db.get_settings())}


# ---------------- tareas programadas ----------------

@app.get("/api/tasks")
async def api_tasks():
    s = db.get_settings()
    st = db.get_state("last_status", {}) or {}
    return {"tasks": worker.task_info(s), "running_task": worker.status["running_task"],
            "discovery_minutes": s["discovery_minutes"], "skip_standby": s["skip_standby"],
            "disks": [{"key": d["key"], "name": d["name"], "label": rules.label(d), "state": d["state"]}
                      for d in st.get("disks", [])],
            "pools": [{"name": p["name"], "scrub": p.get("scrub"), "health": p.get("health")}
                      for p in st.get("pools", []) if "health" in p],
            "zfs": worker.has_zfs(),
            "host_scrubs": await asyncio.to_thread(collector.host_scrub_jobs) if worker.has_zfs() else [],
            "tz": os.environ.get("TZ") or time.strftime("%Z"), "now_h": time.strftime("%H:%M")}


@app.post("/api/tasks/{task_id}/run")
async def api_task_run(task_id: str):
    try:
        started = worker.start_task(task_id)
    except KeyError:
        raise HTTPException(404, _("tarea no encontrada (¿guardaste los cambios?)"))
    if not started:
        raise HTTPException(409, _("hay otra tarea en curso ({t})", t=worker.status["running_task"]))
    return {"ok": True}


@app.post("/api/when-preview")
async def when_preview(body: dict):
    w = body.get("when") or {}
    try:
        nxt = sched.next_runs(w, 3)
    except (ValueError, TypeError) as e:
        return {"valid": False, "error": str(e), "describe": "", "next": []}
    return {"valid": True, "describe": sched.describe(w), "next": nxt, "next_h": [worker.when_h(t) for t in nxt]}


@app.post("/api/zfs/{pool}/scrub")
async def api_scrub(pool: str, body: dict):
    action = body.get("action", "start")
    if action not in ("start", "stop", "pause"):
        raise HTTPException(400, _("acción inválida"))
    if action == "start":
        res = await worker.run_scrubs([pool], True, "manual")
        if not res:
            raise HTTPException(404, _("pool no encontrado"))
        r = res[0]
        if not r["ok"]:
            raise HTTPException(409, r["msg"])
        return {"ok": True, "msg": r["msg"]}
    ok, msg = await asyncio.to_thread(collector.scrub, pool, action)
    if not ok:
        raise HTTPException(409, msg)
    if action == "stop":
        track = db.get_state("scrub_track", {}) or {}
        track[pool] = {"active": False}
        db.set_state("scrub_track", track)
    await worker.zfs_watch()
    return {"ok": True, "msg": msg}


@app.post("/api/test/{channel}")
async def test_channel(channel: str, body: dict | None = None):
    if channel not in ("telegram", "email", "apprise", "report"):
        raise HTTPException(400, _("canal inválido"))
    s = db.get_settings()
    if channel == "report":
        msg = worker.report_message(s)
        return {"results": await worker.send(s, msg)}
    name = {"telegram": "Telegram", "email": _("el correo"), "apprise": "Apprise"}[channel]
    msg = {"title": f"{worker.server_name(s)} · " + _("Prueba de avisos"), "severity": "ok",
           "lead": _("Si lees esto, los avisos por {name} funcionan.", name=name), "sections": [],
           "footer": time.strftime("%d-%m-%Y %H:%M:%S"), "link": s.get("base_url") or None}
    return {"results": await worker.send(s, msg, only=channel)}
