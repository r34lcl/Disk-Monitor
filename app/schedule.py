"""Horarios "amigables" de las tareas programadas → cron, descripción en español y próximas ejecuciones.

when = {"freq": "interval", "every": 30, "unit": "min"|"h"}
     | {"freq": "daily",   "time": "04:00"}
     | {"freq": "weekly",  "days": [0..6], "time": "04:00"}          (0 = domingo, como cron)
     | {"freq": "monthly", "day": 1..31, "time": "01:00"}
     | {"freq": "monthly_nth", "nth": 1..4, "dow": 0..6, "time": "02:00"}   (p.ej. 2º domingo)
     | {"freq": "cron",    "cron": "0 4 * * 3"}
"""
from __future__ import annotations

import re
import time
from datetime import datetime

from croniter import croniter

DOW = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"]
DOW_PL = ["domingos", "lunes", "martes", "miércoles", "jueves", "viernes", "sábados"]
DOW_S = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"]
NTH = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto"}


def _hm(t: str) -> tuple[int, int]:
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(t or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"hora inválida: {t!r} (usa HH:MM)")
    return int(m.group(1)), int(m.group(2))


def interval_seconds(w: dict) -> float | None:
    if w.get("freq") != "interval":
        return None
    n = float(w.get("every") or 0)
    return n * (3600 if w.get("unit") == "h" else 60)


def to_cron(w: dict) -> str | None:
    """None para intervalos. Lanza ValueError si el horario no es válido."""
    f = w.get("freq")
    if f == "interval":
        s = interval_seconds(w) or 0
        if not 60 <= s <= 7 * 86400:
            raise ValueError("el intervalo debe estar entre 1 minuto y 7 días")
        return None
    if f == "cron":
        expr = (w.get("cron") or "").strip()
        if not croniter.is_valid(expr):
            raise ValueError(f"expresión cron inválida: {expr!r}")
        return expr
    h, m = _hm(w.get("time"))
    if f == "daily":
        return f"{m} {h} * * *"
    if f == "weekly":
        days = sorted({int(d) for d in (w.get("days") or []) if 0 <= int(d) <= 6})
        if not days:
            raise ValueError("elige al menos un día de la semana")
        return f"{m} {h} * * {','.join(map(str, days))}"
    if f == "monthly":
        d = int(w.get("day") or 0)
        if not 1 <= d <= 31:
            raise ValueError("el día del mes debe estar entre 1 y 31")
        return f"{m} {h} {d} * *"
    if f == "monthly_nth":
        n, dow = int(w.get("nth") or 0), int(w.get("dow") or 0)
        if n not in NTH or not 0 <= dow <= 6:
            raise ValueError("semana o día inválido")
        return f"{m} {h} * * {dow}#{n}"
    raise ValueError(f"frecuencia desconocida: {f!r}")


def describe(w: dict) -> str:
    f = w.get("freq")
    try:
        if f == "interval":
            n = int(w.get("every") or 0)
            u = "hora" if w.get("unit") == "h" else "minuto"
            return f"Cada {u}" if n == 1 else f"Cada {n} {u}s"
        if f == "cron":
            return f"Cron «{w.get('cron')}»"
        h, m = _hm(w.get("time"))
        at = f"a las {h:02d}:{m:02d}"
        if f == "daily":
            return f"Todos los días {at}"
        if f == "weekly":
            days = sorted({int(d) for d in w.get("days") or []})
            if len(days) == 7:
                return f"Todos los días {at}"
            if days == [1, 2, 3, 4, 5]:
                return f"De lunes a viernes {at}"
            names = [DOW_PL[d] for d in days]
            txt = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]
            return f"Los {txt} {at}"
        if f == "monthly":
            return f"El día {int(w['day'])} de cada mes {at}"
        if f == "monthly_nth":
            return f"El {NTH[int(w['nth'])]} {DOW[int(w['dow'])]} de cada mes {at}"
    except (ValueError, KeyError, TypeError):
        pass
    return "Horario inválido"


def cron_next(expr: str, base: float) -> float | None:
    try:
        return croniter(expr, datetime.fromtimestamp(base).astimezone()).get_next(float)
    except (ValueError, KeyError, TypeError):
        return None


def next_runs(w: dict, n: int = 3, last: float | None = None) -> list[float]:
    now = time.time()
    iv = interval_seconds(w)
    if iv:
        start = max(now, (last or 0) + iv)
        return [start + i * iv for i in range(n)]
    expr = to_cron(w)
    out, t = [], now
    for _ in range(n):
        t = cron_next(expr, t)
        if t is None:
            break
        out.append(t)
    return out


def from_cron(expr: str) -> dict:
    """Traduce un cron simple a horario amigable (para migrar la configuración antigua)."""
    p = (expr or "").split()
    if len(p) == 5:
        mi, ho, dom, mon, dow = p
        if (m := re.match(r"^\*/(\d+)$", mi)) and ho == dom == mon == dow == "*":
            return {"freq": "interval", "every": int(m.group(1)), "unit": "min"}
        if mi.isdigit() and ho.isdigit() and mon == "*":
            t = f"{int(ho):02d}:{int(mi):02d}"
            if dom == "*" and dow == "*":
                return {"freq": "daily", "time": t}
            if dom == "*" and re.match(r"^[0-6](,[0-6])*$", dow):
                return {"freq": "weekly", "days": [int(x) for x in dow.split(",")], "time": t}
            if dom.isdigit() and dow == "*":
                return {"freq": "monthly", "day": int(dom), "time": t}
            if dom == "*" and (m := re.match(r"^([0-6])#([1-4])$", dow)):
                return {"freq": "monthly_nth", "nth": int(m.group(2)), "dow": int(m.group(1)), "time": t}
    return {"freq": "cron", "cron": expr}
