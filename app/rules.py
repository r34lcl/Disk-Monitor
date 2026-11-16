"""Convierte el estado leído en problemas (condiciones persistentes) y eventos (cambios puntuales)."""
from __future__ import annotations

import time

SEV_ORDER = {"ok": 0, "info": 1, "warning": 2, "critical": 3}
TEST_ES = {"short offline": "corta", "short": "corta", "extended offline": "larga", "extended": "larga",
           "long": "larga", "conveyance offline": "de transporte"}
POOL_STATE = {"DEGRADED": "degradado, sin redundancia", "FAULTED": "con falla, no disponible",
              "UNAVAIL": "no disponible", "SUSPENDED": "suspendido por errores de E/S", "OFFLINE": "fuera de línea",
              "REMOVED": "disco retirado"}


BRANDS = (("WDC", "WD"), ("WD", "WD"), ("HGST", "HGST"), ("HUH", "HGST"), ("HUS", "HGST"), ("ST", "Seagate"),
          ("TOSHIBA", "Toshiba"), ("SAMSUNG", "Samsung"), ("CT", "Crucial"), ("CRUCIAL", "Crucial"),
          ("INTEL", "Intel"), ("KINGSTON", "Kingston"), ("SANDISK", "SanDisk"), ("MICRON", "Micron"),
          ("KIOXIA", "Kioxia"), ("SK HYNIX", "SK hynix"), ("HITACHI", "Hitachi"), ("MAXTOR", "Maxtor"))


def brand(model: str | None) -> str:
    m = (model or "").strip()
    up = m.upper()
    for pre, name in BRANDS:
        if up.startswith(pre):
            return name
    return m.split()[0] if m else "?"


def size_h(n) -> str:
    """Capacidad comercial redondeada: 12 TB, 2 TB, 480 GB."""
    if not n:
        return ""
    for u, f in (("TB", 1e12), ("GB", 1e9)):
        if n >= f * 0.95:
            v = n / f
            return f"{v:.0f} {u}" if v >= 10 or abs(v - round(v)) < 0.05 else f"{v:.1f} {u}"
    return human(n)


def label(d: dict) -> str:
    """'sdb (HGST 12 TB)' · 'sde (WD SSD 2 TB)'."""
    parts = [brand(d.get("model"))]
    if d.get("kind") in ("SSD", "NVMe"):
        parts.append(d["kind"])
    if (c := size_h(d.get("capacity"))):
        parts.append(c)
    return f"{d['name']} ({' '.join(parts)})"


def ident(d: dict) -> str:
    """Datos para encontrar físicamente el disco."""
    serial = d.get("serial") or ""
    bits = [d.get("model") or ""]
    if serial and set(serial) - {"0"}:
        bits.append(f"serie {serial}")
    return " · ".join(b for b in bits if b)


# qué hacer frente a cada problema (se muestra en los avisos)
HINTS = {
    "unreadable": "Revisa que siga conectado (cable, bahía) y que la controladora lo muestre.",
    "smart_failed": "El propio disco anuncia que va a fallar. Respalda ya y reemplázalo.",
    "prefail_now": "Un indicador crítico bajó del mínimo del fabricante. Respalda y planifica el reemplazo.",
    "prefail_past": "Ocurrió alguna vez en el pasado. Vigila que no se repita.",
    "temp": "Revisa la ventilación del gabinete y que los ventiladores funcionen.",
    "pending": "Lanza una prueba SMART larga. Si el número no baja a 0, respalda y reemplaza el disco.",
    "offline_unc": "Sectores dañados sin corrección. Respalda y planifica el reemplazo.",
    "reallocated": "El disco ya reemplazó sectores dañados por reservas. Si el número sigue subiendo, reemplázalo.",
    "reported_unc": "Hubo lecturas fallidas. Vigila si el número aumenta.",
    "grown_defects": "La lista de defectos del disco SAS creció. Si sigue aumentando, reemplázalo.",
    "scsi_unc": "Errores de lectura/escritura sin corregir. Revisa el disco y su cableado.",
    "wear": "El SSD se acerca al fin de su vida útil. Planifica el reemplazo.",
    "nvme_critical": "El NVMe reporta una condición crítica. Respalda y revisa el detalle en el panel.",
    "nvme_spare": "Al NVMe le quedan pocos bloques de reserva. Planifica el reemplazo.",
    "media_errors": "El NVMe tuvo errores de integridad de datos. Vigila si aumentan.",
    "selftest": "El disco no pasó su autodiagnóstico. Respalda y reemplázalo.",
    "missing": "¿Se desconectó o falló? Si lo retiraste a propósito, usa «Olvidar» en Detectar discos.",
    "zfs_error": "Revisa que ZFS funcione en el servidor (zpool status).",
    "zfs_state": "El pool perdió redundancia: otra falla podría causar pérdida de datos. Reemplaza el disco afectado.",
    "zfs_vdev_errors": "Revisa el disco indicado y su cable. Luego corre un scrub y limpia los contadores con zpool clear.",
    "zfs_data_errors": "Hay archivos dañados. Míralos con zpool status -v y restáuralos del respaldo.",
    "zfs_scrub_errors": "El scrub encontró datos dañados. Revisa los errores por disco en el panel.",
    "zfs_scrub_old": "Programa un scrub en la pestaña Tareas o lánzalo desde el panel.",
    "zfs_full": "Libera espacio: con el pool muy lleno ZFS se vuelve lento.",
    "fs_full": "Libera espacio o amplía el almacenamiento.",
    "inc_crc_errors": "Casi siempre es el cable SATA o el backplane, no el disco. Cambia o reacomoda el cable.",
    "inc_pending": "El disco tiene sectores que no logra leer. Lanza una prueba SMART larga.",
    "inc_reallocated": "Si sigue subiendo en las próximas revisiones, planifica el reemplazo.",
}


def _issue(subject, rule, sev, title, detail="", kind="issue"):
    return {"key": f"{subject}|{rule}", "subject": subject, "rule": rule, "severity": sev,
            "title": title, "detail": detail, "kind": kind, "hint": HINTS.get(rule, "")}


def evaluate(disks: list[dict], pools: list[dict], fss: list[dict], settings: dict,
             known: dict, last_counters: dict, last_selftests: dict) -> tuple[list[dict], list[dict]]:
    """-> (issues, events). Los eventos sólo aparecen cuando un contador sube respecto a la revisión anterior."""
    th = settings["thresholds"]
    ignored = set(settings.get("ignored_disks") or [])
    issues, events = [], []
    present = {d["key"] for d in disks}

    for d in disks:
        k = d["key"]
        if k in ignored:
            continue
        lab = label(d)
        if d["state"] == "error":
            issues.append(_issue(k, "unreadable", "critical", f"{lab}: no responde a la lectura SMART",
                                 d.get("error", "")))
            continue
        if d["state"] in ("standby", "nosmart"):
            continue
        c = d.get("counters") or {}
        fl = d.get("flags") or {}

        if d.get("smart_passed") is False or fl.get("failing"):
            issues.append(_issue(k, "smart_failed", "critical", f"{lab}: el disco reporta que está fallando",
                                 "Estado SMART: FAILED."))
        if fl.get("prefail_now"):
            bad = [a["name"] for a in d.get("attributes", []) if a.get("when_failed") == "now"]
            issues.append(_issue(k, "prefail_now", "critical", f"{lab}: indicador de falla inminente",
                                 ", ".join(bad)))
        elif fl.get("prefail_past"):
            bad = [a["name"] for a in d.get("attributes", []) if a.get("when_failed") == "past"]
            issues.append(_issue(k, "prefail_past", "warning", f"{lab}: tuvo un indicador de falla en el pasado",
                                 ", ".join(bad)))

        # temperatura
        t = d.get("temp")
        if t is not None:
            ssd = d.get("kind") in ("SSD", "NVMe")
            warn, crit = (th["ssd_temp_warn"], th["ssd_temp_crit"]) if ssd else (th["hdd_temp_warn"], th["hdd_temp_crit"])
            if t >= crit:
                issues.append(_issue(k, "temp", "critical", f"{lab}: muy caliente, {t} °C", f"El máximo recomendado es {crit} °C."))
            elif t >= warn:
                issues.append(_issue(k, "temp", "warning", f"{lab}: temperatura alta, {t} °C", f"Se avisa desde {warn} °C."))

        # sectores
        if (v := c.get("pending")) and v >= th["pending_crit"]:
            issues.append(_issue(k, "pending", "critical", f"{lab}: {v} sectores ilegibles",
                                 "Sectores que el disco no logra leer (Current_Pending_Sector). Suele anticipar una falla."))
        if (v := c.get("offline_uncorrectable")) and v >= th["uncorrectable_crit"]:
            issues.append(_issue(k, "offline_unc", "critical", f"{lab}: {v} sectores dañados sin corrección",
                                 "Offline_Uncorrectable."))
        if (v := c.get("reallocated")) is not None and v >= th["reallocated_warn"]:
            sev = "critical" if v >= th["reallocated_crit"] else "warning"
            issues.append(_issue(k, "reallocated", sev, f"{lab}: {v} sectores dañados reemplazados",
                                 f"Reallocated_Sector_Ct. Crítico desde {th['reallocated_crit']}."))
        if (v := c.get("reported_uncorrect")) and v >= th["reported_uncorrect_warn"]:
            issues.append(_issue(k, "reported_unc", "warning", f"{lab}: {v} lecturas fallidas",
                                 "Reported_Uncorrect."))
        # SAS
        if (v := c.get("grown_defects")):
            issues.append(_issue(k, "grown_defects", "critical" if v >= th["reallocated_crit"] else "warning",
                                 f"{lab}: {v} defectos crecidos (grown defect list)"))
        unc = sum(c.get(f"uncorrected_{x}") or 0 for x in ("read", "write", "verify"))
        if unc:
            issues.append(_issue(k, "scsi_unc", "warning", f"{lab}: {unc} errores de E/S sin corregir"))
        # SSD / NVMe
        if (v := c.get("percentage_used")) is not None:
            if v >= th["ssd_wear_crit"]:
                issues.append(_issue(k, "wear", "critical", f"{lab}: desgaste {v}% de la vida útil"))
            elif v >= th["ssd_wear_warn"]:
                issues.append(_issue(k, "wear", "warning", f"{lab}: desgaste {v}% de la vida útil"))
        if c.get("critical_warning"):
            issues.append(_issue(k, "nvme_critical", "critical",
                                 f"{lab}: NVMe critical_warning = {c['critical_warning']:#04x}"))
        spare, spare_t = c.get("available_spare"), c.get("available_spare_threshold")
        if spare is not None and (spare <= (spare_t or 0) or spare < th["nvme_spare_warn"]):
            issues.append(_issue(k, "nvme_spare", "critical" if spare <= (spare_t or 0) else "warning",
                                 f"{lab}: reserva disponible {spare}%"))
        if (v := c.get("media_errors")):
            issues.append(_issue(k, "media_errors", "warning", f"{lab}: {v} errores de medio (NVMe)"))

        # pruebas SMART: la última terminada
        logs = (d.get("selftest") or {}).get("log") or []
        last = next((x for x in logs if x.get("passed") is not None), None)
        if last and last["passed"] is False:
            issues.append(_issue(k, "selftest", "critical", f"{lab}: falló la prueba SMART",
                                 f"{last.get('type')}: {last.get('status')} (hora {last.get('hours')})"))
        if last and last.get("hours") is not None:
            sig = f"{last.get('hours')}|{last.get('type')}|{last.get('status')}"
            prev = last_selftests.get(k)
            if prev is not None and prev != sig:
                events.append(_issue(k, "selftest_done", "info" if last["passed"] else "critical",
                                     f"{lab}: prueba SMART {TEST_ES.get(str(last.get('type')).lower(), last.get('type'))} "
                                     + ("terminada sin problemas" if last["passed"] else "con errores"),
                                     last.get("status") or "", kind="event"))

        # contadores que suben → evento puntual
        prev = last_counters.get(k) or {}
        for ck, name, sev in (("reallocated", "sectores dañados reemplazados", "warning"),
                              ("pending", "sectores ilegibles", "critical"),
                              ("offline_uncorrectable", "sectores dañados sin corrección", "critical"),
                              ("reported_uncorrect", "lecturas fallidas", "warning"),
                              ("crc_errors", "errores de comunicación con el disco", "warning"),
                              ("error_log_count", "errores registrados por el disco", "warning"),
                              ("grown_bad_blocks", "bloques defectuosos nuevos (SSD)", "warning"),
                              ("program_fail", "fallos de programación (SSD)", "warning"),
                              ("erase_fail", "fallos de borrado (SSD)", "warning"),
                              ("grown_defects", "defectos crecidos (SAS)", "warning"),
                              ("uncorrected_read", "errores de lectura sin corregir", "warning"),
                              ("uncorrected_write", "errores de escritura sin corregir", "warning"),
                              ("media_errors", "errores de medio (NVMe)", "warning")):
            now_v, old_v = c.get(ck), prev.get(ck)
            if now_v is not None and old_v is not None and now_v > old_v:
                events.append(_issue(k, f"inc_{ck}", sev, f"{lab}: más {name} ({old_v} → {now_v})",
                                     kind="event"))

    # discos que estaban y ya no aparecen
    for k, info in known.items():
        if k not in present and k not in ignored:
            issues.append(_issue(k, "missing", "critical",
                                 f"Desapareció un disco: {info.get('model', '?')}",
                                 (f"Serie {info.get('serial')}. " if info.get("serial") else "") + f"Era {info.get('dev')}, visto por última vez el "
                                 f"{time.strftime('%d-%m-%Y %H:%M', time.localtime(info.get('last_seen', 0)))}"))

    # ZFS
    for p in pools:
        subj = f"zpool:{p['name']}"
        if p.get("error"):
            issues.append(_issue(subj, "zfs_error", "warning", "No se pudo leer el estado de ZFS", p["error"]))
            continue
        if p["health"] != "ONLINE":
            sev = "critical"    # DEGRADED incluido: en raidz1/mirror ya no queda redundancia
            bad = [f"{_vname(v)}: {VDEV_STATE.get(v['state'], v['state'])}" for v in p["vdevs"]
                   if v["state"] not in ("ONLINE", "AVAIL", "INUSE") and v.get("depth", 0) > 0]
            bad = [b for b, v in zip(bad, [v for v in p["vdevs"] if v["state"] not in ("ONLINE", "AVAIL", "INUSE")
                                           and v.get("depth", 0) > 0]) if v.get("disk")] or bad
            issues.append(_issue(subj, "zfs_state", sev, f"Pool {p['name']}: {POOL_STATE.get(p['health'], p['health'])}",
                                 "; ".join(bad) or p.get("status", "")))
        errs = [v for v in p["vdevs"] if (v["read"] or 0) + (v["write"] or 0) + (v["cksum"] or 0) > 0]
        if errs:
            issues.append(_issue(subj, "zfs_vdev_errors", "warning", f"Pool {p['name']}: errores en los discos",
                                 "; ".join(f"{_vname(v)}: {v['read']} de lectura, {v['write']} de escritura, {v['cksum']} de checksum"
                                           for v in errs)))
        if p.get("errors") and "No known data errors" not in p["errors"]:
            issues.append(_issue(subj, "zfs_data_errors", "critical", f"Pool {p['name']}: hay datos dañados",
                                 p["errors"]))
        sc = p.get("scrub") or {}
        if sc.get("kind") == "scrub" and not (sc.get("in_progress") or sc.get("paused")) and (sc.get("errors") or 0) > 0:
            issues.append(_issue(subj, "zfs_scrub_errors", "warning",
                                 f"Pool {p['name']}: el último scrub encontró {sc['errors']} errores",
                                 f"Reparado: {sc.get('repaired')}."))
        if th.get("scrub_max_days") and not (sc.get("in_progress") or sc.get("paused")):
            age = (time.time() - sc["date"]) / 86400 if sc.get("date") else None
            if age is None or age > th["scrub_max_days"]:
                issues.append(_issue(subj, "zfs_scrub_old", "warning",
                                     f"Pool {p['name']}: sin scrub hace "
                                     + (f"{age:.0f} días" if age is not None else "mucho tiempo"),
                                     f"Se recomienda uno cada {th['scrub_max_days']} días o menos."))
        if p.get("cap", 0) >= th["fs_crit"]:
            issues.append(_issue(subj, "zfs_full", "critical", f"Pool {p['name']} casi lleno: {p['cap']}%", f"Quedan {human(p.get('free'))}."))
        elif p.get("cap", 0) >= th["fs_warn"]:
            issues.append(_issue(subj, "zfs_full", "warning", f"Pool {p['name']} casi lleno: {p['cap']}%", f"Quedan {human(p.get('free'))}."))

    # sistemas de archivos (los zfs ya se cubren por el pool)
    for f in fss:
        if f["fstype"] == "zfs":
            continue
        subj = f"fs:{f['mount']}"
        if f["pct"] >= th["fs_crit"]:
            issues.append(_issue(subj, "fs_full", "critical", f"{f['mount']} casi lleno: {f['pct']:.0f}%",
                                 f"Quedan {human(f['avail'])} libres ({f['source']})."))
        elif f["pct"] >= th["fs_warn"]:
            issues.append(_issue(subj, "fs_full", "warning", f"{f['mount']} casi lleno: {f['pct']:.0f}%",
                                 f"Quedan {human(f['avail'])} libres ({f['source']})."))

    # un mismo problema puede salir dos veces (p.ej. temp) → quedarse con el más grave
    ids = {d["key"]: ident(d) for d in disks}
    for i in issues + events:
        if i["subject"] in ids:
            i["ident"] = ids[i["subject"]]
    uniq: dict[str, dict] = {}
    for i in issues:
        if i["key"] not in uniq or SEV_ORDER[i["severity"]] > SEV_ORDER[uniq[i["key"]]["severity"]]:
            uniq[i["key"]] = i
    return list(uniq.values()), events


VDEV_STATE = {"FAULTED": "con falla", "UNAVAIL": "no disponible", "REMOVED": "retirado", "OFFLINE": "fuera de línea",
              "DEGRADED": "degradado"}


def _vname(v: dict) -> str:
    return v["disk"].rsplit("/", 1)[-1] if v.get("disk") else v["name"].split("/")[-1]


def human(n: float | None) -> str:
    if n is None:
        return "?"
    for u in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1000 or u == "PB":
            return (f"{n:.1f}".removesuffix(".0") + f" {u}") if u != "B" else f"{int(n)} B"
        n /= 1000
    return str(n)
