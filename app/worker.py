"""Planificador: tareas programadas (revisión, pruebas SMART, scrub ZFS, resumen) y conciliación de alertas."""
from __future__ import annotations

import asyncio
import logging
import time

from . import collector, db, notifiers, rules
from . import schedule as sched

log = logging.getLogger("disk-monitor")
SEV = rules.SEV_ORDER
_lock = asyncio.Lock()       # una revisión a la vez
_task_lock = asyncio.Lock()  # una tarea a la vez
wake = asyncio.Event()
status = {"running": False, "running_task": None, "next": {}, "last_error": None}
ZFS_WATCH_SECONDS = 300
TASK_TYPES = {"check": "Revisión de discos", "smart": "Prueba SMART", "scrub": "Scrub ZFS", "report": "Resumen del estado"}


def cron_next(expr: str, base: float) -> float | None:
    return sched.cron_next(expr, base)


def server_name(s: dict) -> str:
    return s.get("server_name") or collector.host_name()


def task_name(t: dict) -> str:
    if t.get("name"):
        return t["name"]
    if t["type"] == "smart":
        return "Prueba SMART " + ("larga" if t.get("test") == "long" else "corta")
    return TASK_TYPES.get(t["type"], t["type"])


# ---------------------------------------------------------------- textos de tiempo

DOW_S = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]   # orden de tm_wday


def ago(ts: float | None) -> str:
    if not ts:
        return "nunca"
    d = time.time() - ts
    if d < 90:
        return "recién"
    if d < 3600:
        return f"hace {d / 60:.0f} min"
    if d < 86400 * 1.5:
        return f"hace {d / 3600:.0f} h"
    return f"hace {d / 86400:.0f} días"


def when_h(ts: float | None) -> str:
    """'hoy 04:00' · 'mañana 04:00' · 'mié 18-11 04:00'."""
    if not ts:
        return "—"
    t, now = time.localtime(ts), time.localtime()
    hm = time.strftime("%H:%M", t)
    days = (time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
            - time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, -1))) / 86400
    if round(days) == 0:
        return f"hoy {hm}"
    if round(days) == 1:
        return f"mañana {hm}"
    return f"{DOW_S[t.tm_wday]} {time.strftime('%d-%m', t)} {hm}"


def dur_h(sec: float | None) -> str:
    if sec is None:
        return "?"
    h, m = int(sec // 3600), int(sec % 3600 // 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def _footer(trigger: str) -> str:
    return f"{time.strftime('%d-%m-%Y %H:%M')} · revisión {trigger}"


# ---------------------------------------------------------------- revisión

async def run_check(trigger: str = "programada") -> dict:
    async with _lock:
        status["running"] = True
        t0 = time.time()
        try:
            res = await _check(trigger, t0)
            status["last_error"] = None
            return res
        except Exception as e:  # noqa: BLE001
            log.exception("falló la revisión")
            status["last_error"] = f"{type(e).__name__}: {e}"
            raise
        finally:
            status["running"] = False
            db.set_state("last_check_ts", time.time())


async def _check(trigger: str, t0: float) -> dict:
    s = db.get_settings()
    disks = await collector.collect_disks(s["skip_standby"])
    pools = await asyncio.to_thread(collector.collect_zfs)
    fss = await asyncio.to_thread(collector.collect_fs, s.get("ignored_mounts") or [])
    prev_status = db.get_state("last_status", {}) or {}
    prev_disks = {d["key"]: d for d in prev_status.get("disks", [])}
    known = db.get_state("known_disks", {}) or {}
    last_counters = db.get_state("last_counters", {}) or {}
    last_selftests = db.get_state("last_selftests", {}) or {}

    # en reposo smartctl no entrega datos: usar la última lectura completa del mismo disco
    blk = await asyncio.to_thread(collector.lsblk_info)
    for i, d in enumerate(disks):
        if d["state"] == "standby":
            b = blk.get(d["dev"]) or {}
            wwn = b.get("wwn")
            match = next((p for p in prev_disks.values() if (wwn and p.get("wwn") == wwn)
                          or (b.get("serial") and p.get("serial") == b.get("serial"))
                          or p.get("dev") == d["dev"]), None)
            if match:
                disks[i] = {**match, "state": "standby", "dev": d["dev"], "name": d["name"],
                            "stale_since": match.get("checked_at")}
            else:
                d.update({"model": (b.get("model") or "?").strip(), "serial": b.get("serial"), "wwn": wwn,
                          "capacity": int(b["size"]) if b.get("size") else None,
                          "key": wwn or f"dev_{d['name']}"})

    member_of = {}
    for p in pools:
        for m in p.get("members", []):
            member_of[m] = p["name"]
    for f in fss:
        if f.get("disk"):
            for d in disks:
                if d["dev"] == f["disk"]:
                    d.setdefault("mounts", []).append(f["mount"])
    for d in disks:
        d["zpool"] = member_of.get(d["dev"])

    issues, events = rules.evaluate(disks, pools, fss, s, known, last_counters, last_selftests)
    now = time.time()

    # detección de discos: nuevos respecto del inventario (en la primera revisión se arma el inventario)
    first_inventory = not known
    new_disks = [d for d in disks if d["state"] != "error" and not d["key"].startswith("dev_")
                 and d["key"] not in known]
    if not first_inventory:
        for d in new_disks:
            events.append({"key": f"{d['key']}|new_disk", "subject": d["key"], "rule": "new_disk",
                           "severity": "info", "kind": "event",
                           "title": f"Disco nuevo conectado: {rules.label(d)}",
                           "detail": " · ".join(x for x in (d.get("kind"), d.get("dev"),
                                                           d.get("transport") and d["transport"].upper()) if x),
                           "ident": rules.ident(d), "hint": ""})

    # memoria de discos vistos (para detectar ausencias) y contadores para comparar en la próxima
    for d in disks:
        if d["state"] in ("ok", "standby", "nosmart") and not d["key"].startswith("dev_"):
            known[d["key"]] = {"model": d.get("model"), "serial": d.get("serial"), "dev": d["dev"],
                               "last_seen": now}
        if d["state"] == "ok":
            last_counters[d["key"]] = {k: v for k, v in (d.get("counters") or {}).items() if isinstance(v, (int, float))}
            logs = (d.get("selftest") or {}).get("log") or []
            last = next((x for x in logs if x.get("passed") is not None), None)
            if last:
                last_selftests[d["key"]] = f"{last.get('hours')}|{last.get('type')}|{last.get('status')}"
    db.set_state("known_disks", known)
    db.set_state("last_counters", last_counters)
    db.set_state("last_selftests", last_selftests)

    notify_msg = reconcile(issues, events, s, now, trigger)
    scrub_msgs = track_scrubs(pools, s)

    # salud por disco / pool / fs = la peor alerta activa
    worst: dict[str, str] = {}
    for a in db.active_alerts().values():
        if SEV[a["severity"]] > SEV.get(worst.get(a["subject"], "ok"), 0):
            worst[a["subject"]] = a["severity"]
    for d in disks:
        d["health"] = ("unknown" if d["state"] == "error" else "nosmart" if d["state"] == "nosmart"
                       else worst.get(d["key"], "ok"))
        if d["key"] in (s.get("ignored_disks") or []):
            d["health"] = "ignored"
    for p in pools:
        p["health_level"] = worst.get(f"zpool:{p['name']}", "ok")
    for f in fss:
        f["health_level"] = worst.get(f"fs:{f['mount']}", "ok")

    missing = [{"key": k, **v} for k, v in known.items() if k not in {d["key"] for d in disks}]
    ts = int(now)
    rows = []
    for d in disks:
        if d["state"] == "ok":
            if d.get("temp") is not None:
                rows.append((ts, d["key"], "temp", d["temp"]))
            for ck in ("reallocated", "pending", "crc_errors", "percentage_used"):
                v = (d.get("counters") or {}).get(ck)
                if v is not None:
                    rows.append((ts, d["key"], ck, v))
    for f in fss:
        rows.append((ts, f"fs:{f['mount']}", "pct", f["pct"]))
    for p in pools:
        if "cap" in p:
            rows.append((ts, f"zpool:{p['name']}", "pct", p["cap"]))
    db.add_metrics(rows)
    db.prune(int(s.get("retention_days") or 120))

    duration = time.time() - t0
    snapshot = {"ts": now, "duration": duration, "trigger": trigger, "server": server_name(s),
                "disks": disks, "pools": pools, "fs": fss, "missing": missing, "env": collector.env_info()}
    db.set_state("last_status", snapshot)
    db.set_state("hw_signature", await asyncio.to_thread(collector.quick_signature))
    if first_inventory:
        log.info("inventario inicial: %d discos (%s)", len(disks), ", ".join(d["name"] for d in disks))
    summary = {"disks": len(disks), "issues": len(issues), "events": len(events),
               "new_disks": [] if first_inventory else [rules.label(d) for d in new_disks],
               "missing": [f"{m.get('model')} ({m.get('serial') or m['key']})" for m in missing],
               "first_inventory": first_inventory,
               "critical": sum(1 for i in issues if i["severity"] == "critical"),
               "warning": sum(1 for i in issues if i["severity"] == "warning"),
               "notified": bool(notify_msg)}
    db.add_run(now, trigger, duration, summary)
    log.info("revisión (%s) en %.1fs: %d discos, %d problemas, %d eventos", trigger, duration,
             len(disks), len(issues), len(events))
    if notify_msg:
        await send(s, notify_msg)
    for m in scrub_msgs:
        await send(s, m)
    return summary


def _item(a: dict, emoji: str | None = None, with_hint: bool = True) -> dict:
    it = {"emoji": emoji or notifiers.SEV_EMOJI.get(a["severity"], "•"), "text": a["title"],
          "detail": a.get("detail") or ""}
    if with_hint and a.get("hint"):
        it["hint"] = a["hint"]
    if with_hint and a.get("ident"):
        it["ident"] = a["ident"]
    return it


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def reconcile(issues: list[dict], events: list[dict], s: dict, now: float, trigger: str = "programada",
              scope: str | None = None) -> dict | None:
    """scope: sólo conciliar alertas cuyo sujeto empiece así (p.ej. "zpool:"), sin tocar las demás."""
    cfg = s["alerts"]
    min_sev = SEV[cfg.get("min_severity", "warning")]
    remind = float(cfg.get("reminder_hours") or 0) * 3600
    active = db.active_alerts()
    if scope:
        active = {k: a for k, a in active.items() if a["subject"].startswith(scope)}
        issues = [i for i in issues if i["subject"].startswith(scope)]
    current = {i["key"]: i for i in issues}
    watch = db.get_state("selftest_watch", {}) or {}
    new, worse, resolved, reminders, evs = [], [], [], [], []

    for k, i in current.items():
        notify_it = SEV[i["severity"]] >= min_sev
        if k not in active:
            db.open_alert(i, now, notify_it)
            if notify_it:
                new.append(i)
            continue
        a = active[k]
        if SEV[i["severity"]] > SEV[a["severity"]]:
            db.touch_alert(a["id"], i, now, notify_it)
            if a["acknowledged"]:
                db.ack_alert(a["id"], False)
            if notify_it:
                worse.append(i)
        elif (remind and notify_it and not a["acknowledged"]
              and now - (a["last_notified"] or a["first_seen"]) >= remind):
            db.touch_alert(a["id"], i, now, True)
            reminders.append({**i, "since": a["first_seen"]})
        else:
            db.touch_alert(a["id"], i, now, False)
    for k, a in active.items():
        if k not in current:
            db.resolve_alert(a["id"], now)
            if cfg.get("notify_resolved", True) and a["last_notified"]:
                resolved.append(a)
    for e in events:
        notify_it = (SEV[e["severity"]] >= min_sev
                     or (e["rule"] == "selftest_done" and (watch.get(e["subject"]) or cfg.get("notify_selftest_ok")))
                     or (e["rule"] == "new_disk" and cfg.get("notify_new_disks", True)))
        if e["rule"] == "selftest_done":
            watch.pop(e["subject"], None)
        db.open_alert(e, now, notify_it)
        if notify_it:
            evs.append(e)
    db.set_state("selftest_watch", watch)

    if not (new or worse or resolved or reminders or evs):
        return None
    for lst in (new, worse, evs, reminders):
        lst.sort(key=lambda x: -SEV[x["severity"]])
    sections = []
    if new:
        sections.append({"heading": "Nuevo", "items": [_item(i) for i in new]})
    if worse:
        sections.append({"heading": "Empeoró", "items": [_item(i) for i in worse]})
    if evs:
        sections.append({"heading": "Cambios", "items": [_item(e) for e in evs]})
    if reminders:
        sections.append({"heading": "Siguen sin resolver",
                         "items": [{**_item(i, with_hint=False), "detail": f"Activo desde {ago(i['since'])}."}
                                   for i in reminders]})
    if resolved:
        sections.append({"heading": "Resuelto", "items": [{"emoji": "✅", "text": a["title"]} for a in resolved]})

    bad = new + worse + [e for e in evs if SEV[e["severity"]] >= SEV["warning"]]
    allsev = [i["severity"] for i in new + worse + evs + reminders]
    top = max(allsev, key=lambda x: SEV[x]) if allsev else "ok"
    still = len(active) - len(resolved) + len(new)
    srv = server_name(s)
    lead = None
    if bad:
        crit = sum(1 for i in bad if i["severity"] == "critical")
        if len(bad) == 1:
            title = f"{srv} · {bad[0]['title']}"
        else:
            title = f"{srv} · {len(bad)} problemas en los discos"
            lead = f"{_plural(crit, 'es grave', 'son graves')}." if crit else None
    elif evs and all(e["rule"] == "new_disk" for e in evs):
        title = f"{srv} · {'Disco nuevo conectado' if len(evs) == 1 else f'{len(evs)} discos nuevos conectados'}"
    elif evs and all(e["rule"] == "selftest_done" for e in evs):
        title = f"{srv} · {'Prueba SMART terminada' if len(evs) == 1 else 'Pruebas SMART terminadas'}"
    elif evs:
        title = f"{srv} · Cambios en los discos"
    elif reminders:
        title = f"{srv} · Recordatorio: {_plural(len(reminders), 'problema sin resolver', 'problemas sin resolver')}"
        lead = "Puedes silenciarlo en la pestaña Alertas del panel."
    else:
        title = f"{srv} · {'Problema resuelto' if len(resolved) == 1 else 'Problemas resueltos'}"
        top = "ok"
        lead = ("Todo vuelve a estar en orden." if still <= 0
                else "Aún queda 1 problema activo." if still == 1 else f"Aún quedan {still} problemas activos.")
    return {"title": title, "severity": top, "lead": lead, "sections": sections, "footer": _footer(trigger),
            "link": s.get("base_url") or None}


async def send(s: dict, msg: dict, only: str | None = None) -> list[dict]:
    if not only and not any(s[c].get("enabled") for c in ("telegram", "email", "apprise")):
        db.add_notification(msg["title"], notifiers.plain_text(msg),
                            [{"channel": "-", "ok": False, "error": "no hay canales activados"}])
        return []
    res = await notifiers.dispatch(s, msg, only)
    db.add_notification(msg["title"], notifiers.plain_text(msg), res)
    for r in res:
        if not r["ok"]:
            log.warning("aviso %s → %s falló: %s", r["channel"], r.get("target"), r.get("error"))
    return res


# ---------------------------------------------------------------- resumen

HEALTH_EMOJI = {"ok": "🟢", "warning": "🟡", "critical": "🔴", "ignored": "⚪", "unknown": "⚫", "nosmart": "⚪"}
POOL_ES = {"ONLINE": "en línea", "DEGRADED": "degradado", "FAULTED": "con falla", "UNAVAIL": "no disponible",
           "SUSPENDED": "suspendido", "OFFLINE": "fuera de línea"}


def scrub_line(sc: dict) -> str:
    if sc.get("in_progress") or sc.get("paused"):
        what = "Resilver" if sc.get("kind") == "resilver" else "Scrub"
        txt = f"{what} {'en pausa' if sc.get('paused') else 'en curso'}"
        if sc.get("progress") is not None:
            txt += f": {sc['progress']:.0f}%"
        if sc.get("eta"):
            txt += f", faltan {dur_h(sc['eta'])}"
        return txt
    if sc.get("kind") == "scrub" and sc.get("date"):
        res = "sin errores" if not sc.get("errors") else f"{sc['errors']} errores"
        return f"Último scrub {ago(sc['date'])}, {res}" + (f" (duró {dur_h(sc['duration'])})" if sc.get("duration") else "")
    return "Sin scrub registrado"


def upcoming(s: dict, limit: int = 4) -> list[dict]:
    out = []
    for t in s.get("tasks") or []:
        at = status["next"].get(f"task:{t['id']}")
        if at and t["type"] != "check":
            out.append((at, t))
    return [{"emoji": "•", "text": f"{task_name(t)}: {when_h(at)}"} for at, t in sorted(out, key=lambda x: x[0])[:limit]]


def report_message(s: dict) -> dict:
    st = db.get_state("last_status", {}) or {}
    active = sorted(db.active_alerts().values(), key=lambda a: -SEV[a["severity"]])
    disks = st.get("disks", [])
    di = []
    for d in disks:
        parts = [rules.label(d).split("(", 1)[-1].rstrip(")")]
        if d.get("temp") is not None:
            parts.append(f"{d['temp']} °C")
        if d.get("power_on_hours"):
            parts.append(f"{d['power_on_hours'] / 24 / 365:.1f} años")
        if d.get("state") == "standby":
            parts.append("en reposo")
        if d.get("zpool"):
            parts.append(d["zpool"])
        elif d.get("mounts"):
            parts.append(", ".join(d["mounts"]))
        di.append({"emoji": HEALTH_EMOJI.get(d.get("health", "ok"), "•"), "name": d["name"], "text": " · ".join(parts)})
    sections = [{"heading": "💽 Discos", "items": di}]
    pi = []
    for p in st.get("pools", []):
        if "health" not in p:
            continue
        lv = p.get("health_level", "ok")
        pi.append({"emoji": HEALTH_EMOJI.get(lv, "•"), "name": p["name"],
                   "text": f"{POOL_ES.get(p['health'], p['health'])} · {p['cap']}% usado · quedan {rules.human(p.get('free'))}",
                   "detail": scrub_line(p.get("scrub") or {})})
    if pi:
        sections.append({"heading": "🗄 Pools ZFS", "items": pi})
    fi = [{"emoji": HEALTH_EMOJI.get(f.get("health_level", "ok"), "•"), "name": f["mount"],
           "text": f"{f['pct']:.0f}% usado · quedan {rules.human(f['avail'])}"}
          for f in st.get("fs", []) if f["fstype"] != "zfs"]
    if fi:
        sections.append({"heading": "📁 Espacio", "items": fi})
    if active:
        sections.append({"heading": "⚠️ Problemas activos", "items": [_item(a, with_hint=False) for a in active]})
    if (up := upcoming(s)):
        sections.append({"heading": "📅 Próximas tareas", "items": up})
    top = max((a["severity"] for a in active), key=lambda x: SEV[x], default="ok")
    ok_disks = sum(1 for d in disks if d.get("health") == "ok")
    if not active:
        lead = f"Todo en orden: {_plural(ok_disks, 'disco sano', 'discos sanos')}."
    else:
        crit = sum(1 for a in active if a["severity"] == "critical")
        lead = f"Hay {_plural(len(active), 'problema activo', 'problemas activos')}" + (f" ({crit} grave{'s' if crit != 1 else ''})." if crit else ".")
    return {"title": f"{server_name(s)} · Estado de los discos", "severity": top, "lead": lead,
            "sections": sections, "footer": f"Revisado {time.strftime('%d-%m-%Y %H:%M', time.localtime(st.get('ts') or time.time()))}",
            "link": s.get("base_url") or None}


# ---------------------------------------------------------------- pruebas SMART

async def run_selftests(job: dict, notify_ok: bool = True) -> list[dict]:
    st = db.get_state("last_status", {}) or {}
    targets = set(job.get("disks") or [])
    out = []
    devs = await asyncio.to_thread(collector.scan_devices)
    types = {d["dev"]: d["type"] for d in devs}
    watch = db.get_state("selftest_watch", {}) or {}
    wait_min = 0
    for d in st.get("disks", []):
        if d["state"] != "ok" or (targets and d["key"] not in targets) or d["dev"] not in types:
            continue
        if (d.get("selftest") or {}).get("running"):
            out.append({"disk": d["name"], "ok": False, "msg": "ya hay una prueba en curso"})
            continue
        ok, msg = await asyncio.to_thread(collector.start_selftest, d["dev"], types[d["dev"]], job["type"])
        out.append({"disk": d["name"], "ok": ok, "msg": msg})
        if ok:
            watch[d["key"]] = bool(notify_ok)
            pm = (d.get("selftest") or {}).get("polling_minutes") or {}
            wait_min = max(wait_min, pm.get("extended" if job["type"] == "long" else job["type"]) or
                           (120 if job["type"] == "long" else 2))
        log.info("prueba SMART %s en %s: %s", job["type"], d["dev"], "iniciada" if ok else msg)
    db.set_state("selftest_watch", watch)
    db.set_state("last_selftest_run", {"ts": time.time(), "type": job["type"], "results": out})
    if wait_min:   # revisar de nuevo cuando deberían haber terminado, para avisar el resultado a tiempo
        add_followup(time.time() + wait_min * 60 + 180)
    return out


def add_followup(ts: float) -> None:
    f = [x for x in db.get_state("followups", []) or [] if x > time.time() - 3600]
    f.append(ts)
    db.set_state("followups", sorted(f)[-20:])
    wake.set()


# ---------------------------------------------------------------- scrub ZFS

def scrub_start_msg(s: dict, started: list[dict], by: str | None) -> dict:
    items = []
    for p in started:
        sc = p.get("scrub") or {}
        prev = (db.get_state("scrub_last_duration", {}) or {}).get(p["name"]) or sc.get("duration")
        if prev:
            det = f"El anterior duró {dur_h(prev)}: debería terminar {when_h(time.time() + prev)}."
        elif sc.get("eta"):
            det = f"ZFS estima que termina {when_h(time.time() + sc['eta'])}."
        else:
            det = ""
        items.append({"emoji": "🔍", "name": p["name"], "text": f"scrub iniciado ({p['cap']}% usado, {rules.human(p.get('alloc'))} a revisar)",
                      "detail": det})
    who = "programado en Disk Monitor" if by and by != "manual" else "iniciado a mano" if by == "manual" else "iniciado fuera de Disk Monitor"
    title = (f"{server_name(s)} · Scrub de {started[0]['name']} iniciado" if len(started) == 1
             else f"{server_name(s)} · Scrub iniciado en {len(started)} pools")
    return {"title": title, "severity": "info", "lead": f"Scrub {who}. Te aviso cuando termine.",
            "sections": [{"heading": "", "items": items}], "footer": time.strftime("%d-%m-%Y %H:%M"),
            "link": s.get("base_url") or None}


async def run_scrubs(targets: list[str], notify_ok: bool, by: str, notify_start: bool = True) -> list[dict]:
    pools = await asyncio.to_thread(collector.collect_zfs)
    track = db.get_state("scrub_track", {}) or {}
    out, started = [], []
    for p in pools:
        if "health" not in p or (targets and p["name"] not in targets):
            continue
        sc = p.get("scrub") or {}
        if sc.get("in_progress"):
            out.append({"pool": p["name"], "ok": False,
                        "msg": f"ya hay un {'resilver' if sc.get('kind') == 'resilver' else 'scrub'} en curso"})
            continue
        if p["health"] != "ONLINE":
            out.append({"pool": p["name"], "ok": False,
                        "msg": f"el pool está {POOL_ES.get(p['health'], p['health'])}: no se inicia para no exigir más a los discos"})
            continue
        ok, msg = await asyncio.to_thread(collector.scrub, p["name"], "start")
        out.append({"pool": p["name"], "ok": ok, "msg": "scrub iniciado" if ok else msg})
        if ok:
            started.append(p)
            track[p["name"]] = {"active": True, "kind": "scrub", "by": by, "notify_ok": bool(notify_ok),
                                "started": time.time()}
        log.info("scrub %s: %s", p["name"], msg)
    db.set_state("scrub_track", track)
    if started:
        wake.set()
        if notify_start:
            s = db.get_settings()
            await send(s, scrub_start_msg(s, started, by))
    return out


def track_scrubs(pools: list[dict], s: dict) -> list[dict]:
    """Detecta scrubs/resilvers que empiezan o terminan (lanzados por Disk Monitor o por fuera)."""
    track = db.get_state("scrub_track", {}) or {}
    items, top, now, ext_started = [], "ok", time.time(), []
    for p in pools:
        if "health" not in p:
            continue
        n, sc = p["name"], p.get("scrub") or {}
        prev = track.get(n) or {}
        if sc.get("kind") == "scrub" and sc.get("duration") and not (sc.get("in_progress") or sc.get("paused")):
            ld = db.get_state("scrub_last_duration", {}) or {}
            if ld.get(n) != sc["duration"]:
                ld[n] = sc["duration"]
                db.set_state("scrub_last_duration", ld)
        active = bool(sc.get("in_progress") or sc.get("paused"))
        if active and not prev.get("active"):
            track[n] = {"active": True, "kind": sc.get("kind"), "by": None, "started": sc.get("started") or now,
                        "notify_ok": bool(s["alerts"].get("notify_scrub_ok", True))}
            log.info("%s en curso en %s (iniciado fuera de Disk Monitor)", sc.get("kind"), n)
            if sc.get("kind") == "scrub" and s["alerts"].get("notify_scrub_ok", True):
                ext_started.append(p)
        elif not active and prev.get("active"):
            track[n] = {"active": False}
            kind = prev.get("kind") or sc.get("kind")
            if sc.get("duration") and kind == "scrub":
                ld = db.get_state("scrub_last_duration", {}) or {}
                ld[n] = sc["duration"]
                db.set_state("scrub_last_duration", ld)
            if sc.get("canceled"):
                it = {"emoji": "⏹", "name": n, "text": "scrub cancelado antes de terminar"}
                sev, notify_it = "info", bool(prev.get("notify_ok"))
            elif kind == "resilver":
                okp = p["health"] == "ONLINE"
                it = {"emoji": "✅" if okp else "🟡", "name": n,
                      "text": "resilver terminado: " + ("el pool recuperó su redundancia" if okp
                                                        else f"el pool sigue {POOL_ES.get(p['health'], p['health'])}"),
                      "detail": f"Duró {dur_h(sc.get('duration'))}." if sc.get("duration") else ""}
                sev, notify_it = ("ok" if okp else "warning"), True
            else:
                errs = sc.get("errors") or 0
                det = f"Duró {dur_h(sc.get('duration'))}. Reparado: {sc.get('repaired') or '0B'}."
                nxt = next((status["next"].get(f"task:{t['id']}") for t in s.get("tasks") or []
                            if t["type"] == "scrub" and t.get("enabled") and (not t.get("targets") or n in t["targets"])), None)
                if nxt:
                    det += f" Próximo: {when_h(nxt)}."
                if errs:
                    it = {"emoji": "🟡", "name": n, "text": f"scrub terminado con {errs} errores", "detail": det,
                          "hint": "Revisa el pool en el panel; zpool status -v muestra los archivos afectados."}
                    sev, notify_it = "warning", True
                else:
                    it = {"emoji": "✅", "name": n, "text": "scrub terminado sin errores", "detail": det}
                    sev, notify_it = "ok", bool(prev.get("notify_ok"))
            db.open_alert({"key": f"zpool:{n}|scrub_done", "subject": f"zpool:{n}", "rule": "scrub_done",
                           "severity": "info" if sev == "ok" else sev, "kind": "event",
                           "title": f"Pool {n}: {it['text']}", "detail": it.get("detail", "")}, now, notify_it)
            if notify_it:
                items.append(it)
                if SEV[sev] > SEV[top]:
                    top = sev
    db.set_state("scrub_track", track)
    msgs = [scrub_start_msg(s, ext_started, None)] if ext_started else []
    if not items:
        return msgs
    title = (f"{server_name(s)} · Scrub de {items[0]['name']} terminado" if len(items) == 1 and "scrub" in items[0]["text"]
             else f"{server_name(s)} · Mantenimiento de ZFS terminado")
    return msgs + [{"title": title, "severity": top, "sections": [{"heading": "", "items": items}],
                    "footer": time.strftime("%d-%m-%Y %H:%M"), "link": s.get("base_url") or None}]


async def zfs_watch() -> None:
    """Cada 5 min (zpool status no despierta discos): avance del scrub en el panel, aviso al iniciar/terminar
    y alertas inmediatas si el pool se degrada o aparecen errores, sin esperar la próxima revisión."""
    pools = await asyncio.to_thread(collector.collect_zfs)
    if not pools:
        return
    s = db.get_settings()
    for m in track_scrubs(pools, s):
        await send(s, m)
    if _lock.locked():
        return                       # hay una revisión completa en curso: ella concilia todo
    async with _lock:
        issues, _ = rules.evaluate([], pools, [], s, {}, {}, {})
        msg = reconcile(issues, [], s, time.time(), "de ZFS (cada 5 min)", scope="zpool:")
        worst: dict[str, str] = {}
        for a in db.active_alerts().values():
            if SEV[a["severity"]] > SEV.get(worst.get(a["subject"], "ok"), 0):
                worst[a["subject"]] = a["severity"]
        st = db.get_state("last_status", {}) or {}
        if st:
            old = {p.get("name"): p for p in st.get("pools", [])}
            for p in pools:
                p["health_level"] = worst.get(f"zpool:{p['name']}", "ok")
                if p["name"] in old and "cap" not in p:
                    p.update({k: v for k, v in old[p["name"]].items() if k not in p})
            st["pools"] = pools
            db.set_state("last_status", st)
    if msg:
        await send(s, msg)


# ---------------------------------------------------------------- tareas

def validate_tasks(tasks: list[dict]) -> None:
    ids = set()
    for t in tasks:
        if t.get("type") not in TASK_TYPES:
            raise ValueError(f"tipo de tarea desconocido: {t.get('type')}")
        if not t.get("id") or t["id"] in ids:
            raise ValueError("cada tarea necesita un id único")
        ids.add(t["id"])
        if t["type"] == "smart" and t.get("test") not in ("short", "long"):
            raise ValueError("la prueba SMART debe ser corta o larga")
        try:
            sched.to_cron(t.get("when") or {})
        except ValueError as e:
            raise ValueError(f"{task_name(t)}: {e}") from None
        if t["type"] in ("smart", "scrub") and sched.interval_seconds(t["when"]) and sched.interval_seconds(t["when"]) < 3600:
            raise ValueError(f"{task_name(t)}: no tiene sentido repetirla más de una vez por hora")


def has_zfs() -> bool:
    return any("health" in p for p in (db.get_state("last_status", {}) or {}).get("pools", []))


def task_info(s: dict) -> list[dict]:
    last = db.get_state("task_last", {}) or {}
    zfs = has_zfs()
    out = []
    for t in s.get("tasks") or []:
        na = t["type"] == "scrub" and not zfs
        try:
            nxt = sched.next_runs(t["when"], 3, _last_ts(t, last)) if t.get("enabled") and not na else []
        except ValueError:
            nxt = []
        out.append({**t, "label": task_name(t), "describe": sched.describe(t["when"]), "next": nxt,
                    "next_h": [when_h(x) for x in nxt],
                    "unavailable": "Este servidor no tiene pools ZFS" if na else None,
                    "last": last.get(t["id"]), "running": status["running_task"] == t["id"]})
    return out


def _last_ts(t: dict, last: dict) -> float:
    ts = (last.get(t["id"]) or {}).get("ts") or 0
    if t["type"] == "check":
        ts = max(ts, db.get_state("last_check_ts", 0) or 0)
    return ts


async def run_task(t: dict, trigger: str = "programada") -> dict:
    async with _task_lock:
        status["running_task"] = t["id"]
        t0 = time.time()
        ok, msg = True, ""
        try:
            if t["type"] == "check":
                r = await run_check(trigger)
                msg = (f"{_plural(r['disks'], 'disco', 'discos')}, "
                       + ("sin problemas" if not r["issues"] else _plural(r["issues"], "problema", "problemas")))
            elif t["type"] == "smart":
                res = await run_selftests({"type": t["test"], "disks": t.get("targets") or []}, t.get("notify_ok", True))
                started = [r["disk"] for r in res if r["ok"]]
                skipped = [f"{r['disk']}: {r['msg']}" for r in res if not r["ok"]]
                ok = bool(started) or not res
                msg = ("Iniciada en " + ", ".join(started) if started else "No se inició en ningún disco") + \
                      (" · " + "; ".join(skipped) if skipped else "")
                if not res:
                    msg = "No hay discos disponibles para la prueba"
            elif t["type"] == "scrub":
                res = await run_scrubs(t.get("targets") or [], t.get("notify_ok", True), task_name(t), t.get("notify_start", True))
                ok = any(r["ok"] for r in res)
                if not res:
                    msg = ("Este servidor no tiene pools ZFS" if not has_zfs()
                           else f"No existe el pool {', '.join(t.get('targets') or [])}")
                else:
                    msg = "; ".join(f"{r['pool']}: {r['msg']}" for r in res)
            elif t["type"] == "report":
                await run_check("resumen")
                s = db.get_settings()
                res = await send(s, report_message(s))
                ok = bool(res) and all(r["ok"] for r in res)
                msg = "Enviado" if ok else ("No hay canales de aviso activados" if not res
                                            else "Falló el envío: " + "; ".join(r.get("error") or "" for r in res if not r["ok"]))
        except Exception as e:  # noqa: BLE001
            log.exception("tarea %s falló", t["id"])
            ok, msg = False, f"{type(e).__name__}: {e}"
        finally:
            status["running_task"] = None
        last = db.get_state("task_last", {}) or {}
        last[t["id"]] = {"ts": t0, "ok": ok, "msg": msg[:500], "dur": time.time() - t0, "trigger": trigger}
        db.set_state("task_last", last)
        wake.set()
        return last[t["id"]]


def start_task(task_id: str) -> bool:
    t = next((x for x in db.get_settings().get("tasks") or [] if x["id"] == task_id), None)
    if not t:
        raise KeyError(task_id)
    if _task_lock.locked():
        return False
    asyncio.create_task(_safe(run_task(t, "manual")))
    return True


# ---------------------------------------------------------------- bucle principal

def compute_next(s: dict, now: float) -> dict:
    nxt = {}
    last = db.get_state("task_last", {}) or {}
    zfs = has_zfs()
    for t in s.get("tasks") or []:
        if not t.get("enabled") or (t["type"] == "scrub" and not zfs):
            continue          # sin pools ZFS el scrub queda inactivo (se reactiva solo si aparece un pool)
        try:
            iv = sched.interval_seconds(t["when"])
            if iv:
                at = max(now, _last_ts(t, last) + iv)
            else:
                at = sched.cron_next(sched.to_cron(t["when"]), now)
        except (ValueError, KeyError, TypeError):
            continue
        if at:
            nxt[f"task:{t['id']}"] = at
            if t["type"] == "check":
                nxt["check"] = min(nxt.get("check", at), at)
    disc = float(s.get("discovery_minutes") or 0)
    if disc > 0:
        nxt["discovery"] = max(now, (status.get("last_discovery") or 0) + disc * 60)
    if (db.get_state("last_status", {}) or {}).get("pools"):
        nxt["zfswatch"] = max(now, (status.get("last_zfswatch") or 0) + ZFS_WATCH_SECONDS)
    if (f := db.get_state("followups", []) or []):
        nxt["followup"] = max(now, min(f))
    return nxt


async def loop() -> None:
    await asyncio.sleep(2)
    # siempre una revisión completa al arrancar: es la detección inicial de discos del servidor
    await _safe(run_check("inicio"))
    status["last_discovery"] = status["last_zfswatch"] = time.time()
    while True:
        s = db.get_settings()
        now = time.time()
        nxt = compute_next(s, now)
        status["next"] = nxt
        due_at = min(nxt.values()) if nxt else now + 3600
        wake.clear()
        try:
            await asyncio.wait_for(wake.wait(), timeout=max(1.0, due_at - time.time()))
            continue          # cambió la configuración o se pidió algo: recalcular
        except asyncio.TimeoutError:
            pass
        now = time.time()
        tasks = {f"task:{t['id']}": t for t in s.get("tasks") or []}
        for job, at in sorted(nxt.items(), key=lambda x: x[1]):
            if at > now + 1 or job == "check":
                continue
            if job in tasks:
                await _safe(run_task(tasks[job]))
            elif job == "discovery":
                status["last_discovery"] = time.time()
                await _safe(discovery_tick())
            elif job == "zfswatch":
                status["last_zfswatch"] = time.time()
                await _safe(zfs_watch())
            elif job == "followup":
                db.set_state("followups", [x for x in db.get_state("followups", []) or [] if x > now + 1])
                if not _lock.locked():
                    await _safe(run_check("seguimiento de prueba SMART"))


async def discovery_tick() -> None:
    """Sondeo liviano: si cambió el hardware (disco conectado o retirado) lanza una revisión completa."""
    if _lock.locked():
        return
    sig = await asyncio.to_thread(collector.quick_signature)
    old = db.get_state("hw_signature")
    if old is not None and sig != old:
        added = sorted(set(sig) - set(old))
        gone = sorted(set(old) - set(sig))
        log.info("cambio de hardware detectado (+%s / -%s): revisión completa", added, gone)
        await run_check("cambio de hardware")


def collector_h(n):
    return rules.human(n) if n else None


async def _safe(coro):
    try:
        return await coro
    except Exception:  # noqa: BLE001
        log.exception("tarea programada falló")
