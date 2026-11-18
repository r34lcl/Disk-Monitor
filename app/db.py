from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

DB_PATH = os.environ.get("DB_PATH", "/data/disk-monitor.db")
_lock = threading.Lock()

DEFAULT_SETTINGS: dict[str, Any] = {
    "language": "en" if os.environ.get("APP_LANG", "").lower().startswith("en") else "es",   # es | en
    "server_name": "",           # vacío = hostname del host
    "base_url": "",              # p.ej. https://discos.midominio.com, para el enlace en los avisos
    "skip_standby": True,          # no despertar discos en reposo (smartctl -n standby)
    # sondeo rápido de cambios de hardware (no despierta discos); 0 = desactivado
    "discovery_minutes": 5,
    "retention_days": 120,
    # tareas programadas (ver app/schedule.py para el formato de "when")
    "tasks": [
        {"id": "check", "type": "check", "enabled": True, "when": {"freq": "interval", "every": 30, "unit": "min"}},
        {"id": "smart-short", "type": "smart", "test": "short", "enabled": True, "targets": [], "notify_ok": False,
         "when": {"freq": "weekly", "days": [3], "time": "04:00"}},
        {"id": "smart-long", "type": "smart", "test": "long", "enabled": False, "targets": [], "notify_ok": True,
         "when": {"freq": "monthly", "day": 1, "time": "01:00"}},
        {"id": "scrub", "type": "scrub", "enabled": False, "targets": [], "notify_ok": True, "notify_start": True,
         "when": {"freq": "monthly_nth", "nth": 2, "dow": 0, "time": "02:00"}},
        {"id": "report", "type": "report", "enabled": False, "when": {"freq": "weekly", "days": [1], "time": "09:00"}},
    ],
    "alerts": {
        "min_severity": "warning",    # warning | critical: desde qué gravedad se avisa
        "notify_resolved": True,
        "reminder_hours": 24,          # 0 = no recordar problemas que siguen activos
        "notify_selftest_ok": False,   # pruebas SMART lanzadas a mano o fuera de Disk Monitor: avisar si terminan bien
        "notify_scrub_ok": True,       # scrubs lanzados fuera de Disk Monitor (p.ej. cron del sistema): avisar al terminar
        "notify_new_disks": True,      # avisar cuando aparece un disco que no estaba en el inventario
    },
    "thresholds": {
        "hdd_temp_warn": 45, "hdd_temp_crit": 55,
        "ssd_temp_warn": 60, "ssd_temp_crit": 70,
        "reallocated_warn": 1, "reallocated_crit": 50,
        "pending_crit": 1,
        "uncorrectable_crit": 1,
        "reported_uncorrect_warn": 1,
        "ssd_wear_warn": 80, "ssd_wear_crit": 95,
        "nvme_spare_warn": 20,
        "fs_warn": 85, "fs_crit": 95,
        "scrub_max_days": 40,          # 0 = no vigilar la antigüedad del último scrub
    },
    "ignored_disks": [],             # claves de disco que no generan alertas
    "ignored_mounts": ["/boot/efi"],
    "telegram": {"enabled": False, "bot_token": "", "chat_ids": "", "silent_warnings": False},
    "email": {"enabled": False, "host": "", "port": 587, "security": "starttls",
              "username": "", "password": "", "from": "", "to": ""},
    "apprise": {"enabled": False, "urls": ""},
}


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with _lock, conn() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS metrics (ts INTEGER, subject TEXT, name TEXT, value REAL);
        CREATE INDEX IF NOT EXISTS metrics_q ON metrics(subject, name, ts);
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            akey TEXT, subject TEXT, rule TEXT, severity TEXT, title TEXT, detail TEXT,
            kind TEXT,               -- issue (condición persistente) | event (aviso puntual)
            first_seen REAL, last_seen REAL, last_notified REAL,
            resolved_at REAL, acknowledged INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS alerts_active ON alerts(resolved_at, akey);
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, trigger TEXT,
            duration REAL, summary TEXT
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, title TEXT, text TEXT, results TEXT
        );
        """)


def _merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def _migrate_tasks(rows: dict) -> list[dict]:
    """Configuración ≤1.0 (schedule / selftests / report con cron) → lista de tareas."""
    from .schedule import from_cron
    tasks = []
    sch = rows.get("schedule") or {}
    if sch.get("mode") == "cron":
        when = from_cron(sch.get("cron", ""))
    else:
        when = {"freq": "interval", "every": int(sch.get("interval_minutes") or 30), "unit": "min"}
    tasks.append({"id": "check", "type": "check", "enabled": True, "when": when})
    for i, j in enumerate(rows.get("selftests") or []):
        tasks.append({"id": f"smart-{j.get('type', 'short')}" + (f"-{i}" if i > 1 else ""), "type": "smart",
                      "test": j.get("type", "short"), "enabled": bool(j.get("enabled")),
                      "targets": j.get("disks") or [], "notify_ok": j.get("type") == "long",
                      "when": from_cron(j.get("cron", ""))})
    tasks.append(dict(DEFAULT_SETTINGS["tasks"][3]))
    rp = rows.get("report") or {}
    tasks.append({"id": "report", "type": "report", "enabled": bool(rp.get("enabled")),
                  "when": from_cron(rp.get("cron") or "0 9 * * 1")})
    return tasks


def get_settings() -> dict:
    with conn() as c:
        rows = {r["key"]: json.loads(r["value"]) for r in c.execute("SELECT key, value FROM settings")}
    if rows and "tasks" not in rows:
        rows["tasks"] = _migrate_tasks(rows)
        with _lock, conn() as c:
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('tasks', ?)", (json.dumps(rows["tasks"]),))
            c.execute("DELETE FROM settings WHERE key IN ('schedule', 'selftests', 'report')")
    return _merge(json.loads(json.dumps(DEFAULT_SETTINGS)), {k: v for k, v in rows.items() if k in DEFAULT_SETTINGS})


_BOUNDS = {"retention_days": (1, 3650), "discovery_minutes": (0, 1440), "alerts.reminder_hours": (0, 8760),
           "email.port": (0, 65535)}
_CHOICES = {"alerts.min_severity": ("warning", "critical"), "email.security": ("starttls", "ssl", "none")}


def validate_settings(new: dict, base: dict | None = None, path: str = "") -> None:
    """Comprueba tipos (según DEFAULT_SETTINGS) y rangos ANTES de guardar; lanza ValueError.
    Las tareas e idioma se validan aparte."""
    from .i18n import _
    base = DEFAULT_SETTINGS if base is None else base
    if not isinstance(new, dict):
        raise ValueError(_("{k}: debe ser un objeto", k=path.rstrip(".") or "settings"))
    for k, v in new.items():
        if k not in base or (not path and k in ("tasks", "language")):
            continue
        d, key = base[k], path + k
        bad = ValueError(_("{k}: valor inválido", k=key))
        if isinstance(d, dict):
            validate_settings(v, d, key + ".")
            continue
        if isinstance(d, bool):
            if not isinstance(v, bool):
                raise bad
        elif isinstance(d, (int, float)):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
                raise bad
            lo, hi = _BOUNDS.get(key, (0, 1_000_000))
            if not lo <= v <= hi:
                raise ValueError(_("{k}: debe estar entre {lo} y {hi}", k=key, lo=lo, hi=hi))
        elif isinstance(d, str):
            if not isinstance(v, str) or len(v) > 20000:
                raise bad
            if key in _CHOICES and v not in _CHOICES[key]:
                raise bad
        elif isinstance(d, list):
            if not isinstance(v, list) or len(v) > 1000 or not all(isinstance(x, str) and len(x) <= 500 for x in v):
                raise bad


def save_settings(new: dict) -> dict:
    merged = _merge(get_settings(), {k: v for k, v in new.items() if k in DEFAULT_SETTINGS})
    with _lock, conn() as c:
        for k, v in merged.items():
            c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (k, json.dumps(v)))
    return merged


def get_state(key: str, default: Any = None) -> Any:
    with conn() as c:
        r = c.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_state(key: str, value: Any) -> None:
    with _lock, conn() as c:
        c.execute("INSERT OR REPLACE INTO state(key, value) VALUES(?, ?)", (key, json.dumps(value)))


# ---------------- métricas (historial para gráficos) ----------------

def add_metrics(rows: list[tuple[int, str, str, float]]) -> None:
    with _lock, conn() as c:
        c.executemany("INSERT INTO metrics(ts, subject, name, value) VALUES(?,?,?,?)", rows)


def get_metrics(subject: str, name: str, since: int) -> list[list]:
    with conn() as c:
        return [[r[0], r[1]] for r in c.execute(
            "SELECT ts, value FROM metrics WHERE subject=? AND name=? AND ts>=? ORDER BY ts",
            (subject, name, since))]


def prune(retention_days: int) -> None:
    cut = time.time() - retention_days * 86400
    with _lock, conn() as c:
        c.execute("DELETE FROM metrics WHERE ts<?", (int(cut),))
        c.execute("DELETE FROM alerts WHERE resolved_at IS NOT NULL AND resolved_at<?", (cut,))
        c.execute("DELETE FROM runs WHERE ts<?", (cut,))
        c.execute("DELETE FROM notifications WHERE ts<?", (cut,))


# ---------------- alertas ----------------

def active_alerts() -> dict[str, dict]:
    with conn() as c:
        return {r["akey"]: dict(r) for r in c.execute(
            "SELECT * FROM alerts WHERE resolved_at IS NULL AND kind='issue'")}


def open_alert(a: dict, now: float, notified: bool) -> int:
    with _lock, conn() as c:
        cur = c.execute(
            "INSERT INTO alerts(akey, subject, rule, severity, title, detail, kind, first_seen, last_seen,"
            " last_notified, resolved_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (a["key"], a["subject"], a["rule"], a["severity"], a["title"], a.get("detail", ""), a["kind"],
             now, now, now if notified else None, now if a["kind"] == "event" else None))
        return cur.lastrowid


def touch_alert(aid: int, a: dict, now: float, notified: bool) -> None:
    with _lock, conn() as c:
        c.execute("UPDATE alerts SET last_seen=?, severity=?, title=?, detail=?"
                  + (", last_notified=?" if notified else "") + " WHERE id=?",
                  (now, a["severity"], a["title"], a.get("detail", ""), *( [now] if notified else []), aid))


def resolve_alert(aid: int, now: float) -> None:
    with _lock, conn() as c:
        c.execute("UPDATE alerts SET resolved_at=? WHERE id=?", (now, aid))


def ack_alert(aid: int, value: bool) -> None:
    with _lock, conn() as c:
        c.execute("UPDATE alerts SET acknowledged=? WHERE id=?", (1 if value else 0, aid))


def list_alerts(limit: int = 300) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM alerts ORDER BY (resolved_at IS NULL) DESC, last_seen DESC LIMIT ?", (limit,))]


def add_run(ts: float, trigger: str, duration: float, summary: dict) -> None:
    with _lock, conn() as c:
        c.execute("INSERT INTO runs(ts, trigger, duration, summary) VALUES(?,?,?,?)",
                  (ts, trigger, duration, json.dumps(summary)))


def list_runs(limit: int = 50) -> list[dict]:
    with conn() as c:
        out = []
        for r in c.execute("SELECT * FROM runs ORDER BY ts DESC LIMIT ?", (limit,)):
            d = dict(r)
            d["summary"] = json.loads(d["summary"] or "{}")
            out.append(d)
        return out


def add_notification(title: str, text: str, results: list) -> None:
    with _lock, conn() as c:
        c.execute("INSERT INTO notifications(ts, title, text, results) VALUES(?,?,?,?)",
                  (time.time(), title, text, json.dumps(results)))


def list_notifications(limit: int = 100) -> list[dict]:
    with conn() as c:
        out = []
        for r in c.execute("SELECT * FROM notifications ORDER BY ts DESC LIMIT ?", (limit,)):
            d = dict(r)
            d["results"] = json.loads(d["results"] or "[]")
            out.append(d)
        return out
