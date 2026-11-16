"""Lee el estado de los discos: SMART (ATA / SCSI-SAS / NVMe), pools ZFS y sistemas de archivos."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time

log = logging.getLogger("disk-monitor")
# el contenedor corre con pid: host → /proc/1 es el init del host (montajes, hostname, raíz)
HOST_PROC = os.environ.get("HOST_PROC", "/proc/1")


def run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} no está instalado"
    except subprocess.TimeoutExpired:
        return 124, "", f"tiempo de espera agotado ({timeout}s)"


def host_name() -> str:
    for p in (f"{HOST_PROC}/root/etc/hostname", "/etc/hostname"):
        try:
            with open(p) as f:
                if (n := f.read().strip()):
                    return n
        except OSError:
            pass
    return os.uname().nodename


# ---------------------------------------------------------------- SMART

def scan_devices() -> list[dict]:
    rc, out, err = run(["smartctl", "-j", "--scan-open"], 60)
    try:
        devs = json.loads(out).get("devices", [])
    except json.JSONDecodeError:
        log.error("smartctl --scan-open falló: %s", err or out[:300])
        devs = []
    seen, res = set(), []
    for d in devs:
        ident = (d["name"], d.get("type", "auto"))
        if ident in seen:
            continue
        seen.add(ident)
        typ = d.get("type", "auto")
        raid = bool(re.match(r"^(megaraid|cciss|areca|aacraid|3ware|hpt|sssraid),", typ))
        name = os.path.basename(d["name"])
        if raid:            # discos físicos detrás de una controladora RAID por hardware
            name = f"{name}:{typ.replace(',', '')}"
        res.append({"dev": d["name"], "type": typ, "protocol": d.get("protocol", ""), "name": name, "raid": raid})
    return res


def quick_signature() -> list[str]:
    """Huella barata del hardware (no abre los discos ni los despierta): sirve para notar
    discos conectados/retirados entre revisiones completas."""
    sig = set()
    rc, out, _ = run(["smartctl", "-j", "--scan"], 30)
    try:
        for d in json.loads(out).get("devices", []):
            sig.add(f"scan:{d['name']}|{d.get('type')}")
    except json.JSONDecodeError:
        pass
    for name, b in lsblk_info().items():
        if b.get("type") == "disk" and not re.match(r"^/dev/(loop|ram|zram|zd|nbd|dm-|md)", name):
            sig.add(f"blk:{name}|{b.get('serial')}|{b.get('wwn')}|{b.get('size')}")
    return sorted(sig)


def lsblk_info() -> dict[str, dict]:
    rc, out, _ = run(["lsblk", "-J", "-b", "-d", "-o", "NAME,SIZE,MODEL,SERIAL,TRAN,ROTA,TYPE,WWN,HCTL"], 30)
    try:
        return {f"/dev/{b['name']}": b for b in json.loads(out).get("blockdevices", [])}
    except json.JSONDecodeError:
        return {}


def _attr_map(j: dict) -> dict[int, dict]:
    return {a["id"]: a for a in (j.get("ata_smart_attributes") or {}).get("table", [])}


def _devstat(j: dict, name: str):
    for p in (j.get("ata_device_statistics") or {}).get("pages", []):
        for t in p.get("table", []):
            if t.get("name") == name and (t.get("flags") or {}).get("valid", True):
                return t.get("value")
    return None


def _raw(attrs: dict, i: int):
    a = attrs.get(i)
    if not a:
        return None
    v = a["raw"]["value"]
    # algunos atributos (temperatura, horas) traen min/max empaquetados en los bytes altos
    if i in (190, 194, 231):
        return v & 0xFF
    if i == 9:
        return v & 0xFFFFFFFF
    return v


def _wwn(j: dict) -> str | None:
    w = j.get("wwn")
    if not w:
        return None
    return f"0x{w['naa']:x}{w['oui']:06x}{w['id']:09x}"


def _bogus_serial(s: str | None) -> bool:
    return not s or set(s.strip()) <= {"0", " ", "-", "F", "f"}


def disk_key(j: dict, dev: str) -> str:
    if (w := _wwn(j)):
        return w
    serial = j.get("serial_number")
    if not _bogus_serial(serial):
        return f"{j.get('model_name', 'disk')}_{serial}".replace(" ", "_")
    return f"dev_{dev}"


STANDBY_RE = re.compile(r"STANDBY|SLEEP|IDLE", re.I)


def read_smart(dev: dict, skip_standby: bool) -> dict:
    cmd = ["smartctl", "-j", "-x", "-d", dev["type"]]
    if skip_standby:
        cmd += ["-n", "standby"]
    rc, out, err = run(cmd + [dev["dev"]], 180)
    try:
        j = json.loads(out)
    except json.JSONDecodeError:
        nm = dev.get("name") or os.path.basename(dev["dev"])
        return {"dev": dev["dev"], "dtype": dev["type"], "name": nm, "key": f"dev_{nm}",
                "state": "error", "error": (err or out or f"smartctl rc={rc}").strip()[:500], "raw": None}
    return parse_smart(j, dev)


def parse_smart(j: dict, dev: dict) -> dict:
    sc = j.get("smartctl") or {}
    exit_status = sc.get("exit_status", 0)
    msgs = [m.get("string", "") for m in sc.get("messages", [])]
    name = dev.get("name") or os.path.basename(dev["dev"])
    d: dict = {
        "dev": dev["dev"], "name": name, "key": disk_key(j, name), "raid": dev.get("raid", False),
        "model": j.get("model_name") or j.get("scsi_model_name") or j.get("model_family") or "?",
        "family": j.get("model_family"),
        "vendor": j.get("vendor") or j.get("scsi_vendor"),
        "serial": j.get("serial_number"), "wwn": _wwn(j),
        "firmware": j.get("firmware_version") or j.get("scsi_revision"),
        "capacity": (j.get("user_capacity") or {}).get("bytes")
                    or (j.get("nvme_total_capacity")) or None,
        "protocol": (j.get("device") or {}).get("protocol") or dev.get("protocol"),
        "dtype": (j.get("device") or {}).get("type") or dev.get("type"),
        "rpm": j.get("rotation_rate"),
        "form_factor": (j.get("form_factor") or {}).get("name"),
        "link": ((j.get("interface_speed") or {}).get("current") or {}).get("string"),
        "exit_status": exit_status, "messages": msgs,
        "state": "ok", "smart_passed": (j.get("smart_status") or {}).get("passed"),
        "temp": (j.get("temperature") or {}).get("current"),
        "temp_lifetime_max": (j.get("temperature") or {}).get("lifetime_max"),
        "temp_limit": (j.get("temperature") or {}).get("op_limit_max"),
        "power_on_hours": (j.get("power_on_time") or {}).get("hours") or None,
        "power_cycles": j.get("power_cycle_count"),
        "counters": {}, "attributes": [], "selftest": {"running": False, "log": []},
        "error_log": [],
        "checked_at": time.time(),
    }
    if exit_status & 0b10 and any(STANDBY_RE.search(m) for m in msgs):
        d["state"] = "standby"
        return d
    if exit_status & 0b11 and not j.get("smart_status"):
        d["state"] = "error"
        d["error"] = "; ".join(msgs) or f"smartctl rc={exit_status}"
        return d

    if (not j.get("smart_status") and not j.get("ata_smart_attributes")
            and not j.get("nvme_smart_health_information_log") and "scsi_grown_defect_list" not in j):
        d["state"] = "nosmart"
        d["error"] = "; ".join(msgs) or "el dispositivo no entrega datos SMART"
        d["kind"] = "SSD" if d["rpm"] == 0 else ("HDD" if d["rpm"] else "?")
        return d

    proto = (d["protocol"] or "").upper()
    if proto == "NVME" or "nvme_smart_health_information_log" in j:
        d["kind"] = "NVMe"
        _parse_nvme(j, d)
    elif proto == "SCSI" or "scsi_grown_defect_list" in j:
        d["kind"] = "SSD" if d["rpm"] == 0 else "HDD"
        _parse_scsi(j, d)
    else:
        d["kind"] = "SSD" if d["rpm"] == 0 else "HDD"
        _parse_ata(j, d)
    # bits de smartctl: 3 = SMART "FAILING", 4 = atributo pre-falla bajo umbral, 5 = bajo umbral en el pasado
    d["flags"] = {"failing": bool(exit_status & 8), "prefail_now": bool(exit_status & 16),
                  "prefail_past": bool(exit_status & 32), "errlog": bool(exit_status & 64),
                  "selftest_errors": bool(exit_status & 128)}
    return d


def _parse_ata(j: dict, d: dict) -> None:
    attrs = _attr_map(j)
    c = d["counters"]
    c["reallocated"] = _raw(attrs, 5)
    c["realloc_events"] = _raw(attrs, 196)
    c["pending"] = _raw(attrs, 197)
    c["offline_uncorrectable"] = _raw(attrs, 198)
    c["reported_uncorrect"] = _raw(attrs, 187)
    c["crc_errors"] = _raw(attrs, 199)
    c["grown_bad_blocks"] = _raw(attrs, 170) if d["kind"] == "SSD" else None
    c["program_fail"] = _raw(attrs, 171) if d["kind"] == "SSD" else None
    c["erase_fail"] = _raw(attrs, 172) if d["kind"] == "SSD" else None
    c["error_log_count"] = ((j.get("ata_smart_error_log") or {}).get("extended")
                            or (j.get("ata_smart_error_log") or {}).get("summary") or {}).get("count", 0)
    wear = _devstat(j, "Percentage Used Endurance Indicator")
    if wear is not None and d["kind"] == "SSD":
        c["percentage_used"] = wear
    elif d["kind"] == "SSD" and 233 in attrs and "Wear" in attrs[233]["name"]:
        c["percentage_used"] = 100 - attrs[233]["value"]
    if not d["power_on_hours"]:
        d["power_on_hours"] = _raw(attrs, 9) or _devstat(j, "Power-on Hours")
    if d["power_cycles"] is None:
        d["power_cycles"] = _raw(attrs, 12)
    if d["temp"] is None:
        d["temp"] = _raw(attrs, 194) or _raw(attrs, 190)
    lbs = j.get("logical_block_size") or 512
    w, r = _devstat(j, "Logical Sectors Written"), _devstat(j, "Logical Sectors Read")
    c["bytes_written"] = w * lbs if w else None
    c["bytes_read"] = r * lbs if r else None
    for a in attrs.values():
        d["attributes"].append({
            "id": a["id"], "name": a["name"], "value": a.get("value"), "worst": a.get("worst"),
            "thresh": a.get("thresh"), "when_failed": a.get("when_failed") or "",
            "prefail": (a.get("flags") or {}).get("prefailure", False), "raw": a["raw"].get("string"),
        })
    st = (j.get("ata_smart_data") or {}).get("self_test") or {}
    status = st.get("status") or {}
    if "remaining_percent" in status or 240 <= (status.get("value") or 0) <= 255:
        d["selftest"]["running"] = True
        d["selftest"]["remaining"] = status.get("remaining_percent")
    d["selftest"]["polling_minutes"] = st.get("polling_minutes")
    stlog = (j.get("ata_smart_self_test_log") or {})
    table = (stlog.get("extended") or {}).get("table") or (stlog.get("standard") or {}).get("table") or []
    for t in table[:20]:
        s = t.get("status") or {}
        d["selftest"]["log"].append({
            "type": (t.get("type") or {}).get("string"), "status": s.get("string"),
            "passed": s.get("passed"), "hours": t.get("lifetime_hours"),
            "lba": t.get("lba"),
        })
    errlog = (j.get("ata_smart_error_log") or {}).get("extended") or (j.get("ata_smart_error_log") or {}).get("summary") or {}
    for e in (errlog.get("table") or [])[:10]:
        d["error_log"].append({"n": e.get("error_number"), "hours": e.get("lifetime_hours"),
                               "desc": (e.get("error_description") or "")})


def _parse_scsi(j: dict, d: dict) -> None:
    c = d["counters"]
    c["grown_defects"] = j.get("scsi_grown_defect_list")
    ec = j.get("scsi_error_counter_log") or {}
    for k in ("read", "write", "verify"):
        if k in ec:
            c[f"uncorrected_{k}"] = ec[k].get("total_uncorrected_errors")
    c["non_medium_errors"] = (j.get("scsi_nonmedium_error") or {}).get("count")
    if not d["power_on_hours"]:
        d["power_on_hours"] = (j.get("power_on_time") or {}).get("hours")
    ss = j.get("scsi_start_stop_cycle_counter") or {}
    d["power_cycles"] = d["power_cycles"] or ss.get("accumulated_start_stop_cycles")
    if (pe := j.get("scsi_percentage_used_endurance_indicator")) is not None:
        c["percentage_used"] = pe
    for k, v in ec.items():
        if isinstance(v, dict):
            d["attributes"].append({"id": k, "name": f"Errores {k}", "value": None, "worst": None, "thresh": None,
                                    "when_failed": "", "prefail": False,
                                    "raw": f"corregidos {v.get('total_errors_corrected', 0)}, sin corregir "
                                           f"{v.get('total_uncorrected_errors', 0)}, "
                                           f"{v.get('gigabytes_processed', '?')} GB procesados"})
    for i in range(20):
        t = j.get(f"scsi_self_test_{i}")
        if not t:
            break
        res = t.get("result") or {}
        d["selftest"]["log"].append({"type": (t.get("code") or {}).get("string"), "status": res.get("string"),
                                     "passed": res.get("value") == 0 if "value" in res else None,
                                     "hours": (t.get("power_on_time") or {}).get("hours")})
    if j.get("self_test_in_progress") or "in progress" in str((j.get("scsi_self_test_0") or {}).get("result")):
        d["selftest"]["running"] = True


def _parse_nvme(j: dict, d: dict) -> None:
    h = j.get("nvme_smart_health_information_log") or {}
    c = d["counters"]
    c["critical_warning"] = h.get("critical_warning")
    c["available_spare"] = h.get("available_spare")
    c["available_spare_threshold"] = h.get("available_spare_threshold")
    c["percentage_used"] = h.get("percentage_used")
    c["media_errors"] = h.get("media_errors")
    c["error_log_count"] = h.get("num_err_log_entries")
    c["unsafe_shutdowns"] = h.get("unsafe_shutdowns")
    if h.get("data_units_written") is not None:
        c["bytes_written"] = h["data_units_written"] * 512000
        c["bytes_read"] = h.get("data_units_read", 0) * 512000
    d["power_on_hours"] = d["power_on_hours"] or h.get("power_on_hours")
    d["power_cycles"] = d["power_cycles"] or h.get("power_cycles")
    if d["temp"] is None:
        d["temp"] = h.get("temperature")
    if not d["capacity"]:
        d["capacity"] = (j.get("nvme_namespaces") or [{}])[0].get("size", {}).get("bytes")
    for k, v in h.items():
        if not isinstance(v, (dict, list)):
            d["attributes"].append({"id": "", "name": k, "value": None, "worst": None, "thresh": None,
                                    "when_failed": "", "prefail": False, "raw": str(v)})
    stl = j.get("nvme_self_test_log") or {}
    if stl.get("current_self_test_operation", {}).get("value"):
        d["selftest"]["running"] = True
        d["selftest"]["remaining"] = 100 - (stl.get("current_self_test_completion_percent") or 0)
    for t in (stl.get("table") or [])[:20]:
        res = t.get("self_test_result") or {}
        d["selftest"]["log"].append({"type": (t.get("self_test_code") or {}).get("string"),
                                     "status": res.get("string"), "passed": res.get("value") == 0,
                                     "hours": t.get("power_on_hours")})


async def collect_disks(skip_standby: bool) -> list[dict]:
    devs = await asyncio.to_thread(scan_devices)
    blk = await asyncio.to_thread(lsblk_info)
    disks = await asyncio.gather(*(asyncio.to_thread(read_smart, d, skip_standby) for d in devs))
    for d in disks:
        b = {} if d.get("raid") else (blk.get(d["dev"]) or blk.get(d["dev"] + "n1") or {})
        d["transport"] = b.get("tran")
        d["hctl"] = b.get("hctl")
        if not d.get("capacity") and b.get("size"):
            d["capacity"] = int(b["size"])
        if d.get("model") in (None, "?") and b.get("model"):
            d["model"] = b["model"].strip()
    return sorted(disks, key=lambda x: x["dev"])


def start_selftest(dev: str, dtype: str, kind: str) -> tuple[bool, str]:
    rc, out, err = run(["smartctl", "-d", dtype, "-t", kind, dev], 60)
    txt = (out + err).strip()
    ok = rc & 0b11 == 0 and ("has begun" in txt or "Self-test" in txt or "Testing has begun" in txt)
    lines = [l for l in txt.splitlines() if l.strip() and not l.startswith(("smartctl ", "Copyright"))]
    return ok, "\n".join(lines[-4:])


# ---------------------------------------------------------------- ZFS

POOL_RE = re.compile(r"^\s*pool:\s*(\S+)")


def _base_disk(path: str) -> str | None:
    """/dev/disk/by-id/...-part1 → /dev/sda ; /dev/nvme0n1p2 → /dev/nvme0 (como lo nombra smartctl)."""
    root = f"{HOST_PROC}/root"
    real = os.path.realpath(root + path) if os.path.exists(root + path) else os.path.realpath(path)
    if real.startswith(root):
        real = real[len(root):]
    name = os.path.basename(real)
    if not real.startswith("/dev/"):
        return None
    if (m := re.match(r"^(nvme\d+)n\d+(p\d+)?$", name)):
        return f"/dev/{m.group(1)}"
    if (m := re.match(r"^(mmcblk\d+)(p\d+)?$", name)):
        return f"/dev/{m.group(1)}"
    m = re.match(r"^([a-z]+?)(\d+)?$", name)
    return f"/dev/{m.group(1)}" if m else real


ZFS_MODE = {"mode": None}


def zpool(*args: str) -> tuple[int, str, str]:
    """Usa el zpool del host (misma versión que su módulo ZFS) vía nsenter; si el host no lo tiene,
    el del contenedor. Sin /dev/zfs no hay ZFS en este servidor."""
    if not os.path.exists("/dev/zfs"):
        ZFS_MODE["mode"] = "no disponible"
        return 127, "", "no zfs"
    rc, out, err = run(["nsenter", "-t", "1", "-m", "--", "zpool", *args], 60)
    if rc not in (126, 127) and "No such file" not in err and "Operation not permitted" not in err:
        ZFS_MODE["mode"] = "zpool del host"
        return rc, out, err
    ZFS_MODE["mode"] = "zpool del contenedor"
    return run(["zpool", *args], 60)


def env_info() -> dict:
    rc, out, _ = run(["smartctl", "--version"], 10)
    ver = out.splitlines()[0].split(" [")[0] if out else "?"
    return {"smartctl": ver, "zfs": ZFS_MODE["mode"] or "?", "host": host_name(),
            "kernel": os.uname().release}


def collect_zfs() -> list[dict]:
    rc, out, err = zpool("list", "-Hp", "-o", "name,size,alloc,free,frag,cap,health")
    if rc != 0 or not out.strip():
        if rc == 127 or not out.strip() and "no pools" in (out + err).lower() or rc == 0:
            return []
        return [{"name": "?", "error": (err or out).strip()[:300]}]
    pools = {}
    for line in out.strip().splitlines():
        n, size, alloc, free, frag, cap, health = line.split("\t")
        pools[n] = {"name": n, "size": int(size), "alloc": int(alloc), "free": int(free),
                    "frag": None if frag == "-" else int(frag), "cap": int(cap), "health": health,
                    "vdevs": [], "scan": "", "status": "", "errors": "", "members": []}
    rc, out, err = zpool("status", "-P", "-p")
    cur, section, in_config = None, None, False
    for line in out.splitlines():
        if (m := POOL_RE.match(line)):
            cur = pools.get(m.group(1))
            in_config = False
            section = None
            continue
        if cur is None:
            continue
        s = line.strip()
        km = re.match(r"^\s*(state|status|action|see|scan|config|errors):\s?(.*)$", line)
        if km and (not in_config or km.group(1) == "errors"):
            section = km.group(1)
            in_config = section == "config"
            if section in ("status", "scan", "errors", "action"):
                cur[section] = km.group(2).strip()
            continue
        if in_config:
            if not s or s.startswith("NAME"):
                continue
            parts = s.split()
            lead = line.lstrip("\t")
            depth = (len(lead) - len(lead.lstrip(" "))) // 2
            v = {"name": parts[0], "state": parts[1] if len(parts) > 1 else "",
                 "read": _num(parts, 2), "write": _num(parts, 3), "cksum": _num(parts, 4),
                 "note": " ".join(parts[5:]), "depth": depth, "disk": None}
            if parts[0].startswith("/dev/"):
                v["disk"] = _base_disk(parts[0])
                cur["members"].append(v["disk"])
            cur["vdevs"].append(v)
        elif section in ("status", "scan", "action") and s:
            cur[section] += " " + s
    for p in pools.values():
        p["scrub"] = _parse_scan(p.get("scan", ""))
    return list(pools.values())


def _num(parts, i):
    try:
        return int(parts[i])
    except (IndexError, ValueError):
        return None


MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def _parse_date(s: str) -> float | None:
    m = re.search(r"(\w{3})\s+(\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})\s+(\d{4})", s)
    if not m or m.group(1) not in MONTHS:
        return None
    return time.mktime((int(m.group(6)), MONTHS[m.group(1)], int(m.group(2)),
                        int(m.group(3)), int(m.group(4)), int(m.group(5)), 0, 0, -1))


def _dur(txt: str) -> float | None:
    """'13:01:03' o '1 days 02:03:04' → segundos."""
    m = re.search(r"(?:(\d+) days? )?(\d+):(\d{2}):(\d{2})", txt or "")
    if not m:
        return None
    return int(m.group(1) or 0) * 86400 + int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4))


def _parse_scan(scan: str) -> dict:
    r = {"text": scan, "in_progress": "in progress" in scan, "paused": "paused" in scan,
         "canceled": "canceled" in scan, "kind": None, "date": None, "errors": None, "repaired": None,
         "duration": None, "progress": None, "eta": None}
    if scan.startswith("scrub"):
        r["kind"] = "scrub"
    elif scan.startswith("resilver"):
        r["kind"] = "resilver"
    if (m := re.search(r"repaired (\S+) in (.*?) with (\d+) errors on (.+)$", scan)):
        r["repaired"], r["errors"], r["date"] = m.group(1), int(m.group(3)), _parse_date(m.group(4))
        r["duration"] = _dur(m.group(2))
    elif r["canceled"] and (m := re.search(r"canceled on (.+)$", scan)):
        r["canceled_at"] = _parse_date(m.group(1))
    elif (r["in_progress"] or r["paused"]) and (m := re.search(r"since (.+?)(\s{2,}|$)", scan)):
        r["started"] = _parse_date(m.group(1))
        if (p := re.search(r"([\d.]+)% done", scan)):
            r["progress"] = float(p.group(1))
        if (e := re.search(r"([\d:]+(?: days? [\d:]+)?|\d+ days? \S+) to go", scan)):
            r["eta"] = _dur(e.group(1))
    return r


def scrub(pool: str, action: str = "start") -> tuple[bool, str]:
    """action: start | stop | pause. Usa el zpool del host."""
    flag = {"start": [], "stop": ["-s"], "pause": ["-p"]}[action]
    rc, out, err = zpool("scrub", *flag, pool)
    txt = (out + err).strip()
    return rc == 0, txt or {"start": "scrub iniciado", "stop": "scrub detenido", "pause": "scrub en pausa"}[action]


# ---------------------------------------------------------------- sistemas de archivos

FS_TYPES = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "vfat", "exfat", "ntfs", "ntfs3", "f2fs", "jfs", "reiserfs"}


def _unescape(s: str) -> str:
    return re.sub(r"\\(\d{3})", lambda m: chr(int(m.group(1), 8)), s)


def collect_fs(ignored: list[str]) -> list[dict]:
    try:
        with open(f"{HOST_PROC}/mounts") as f:
            lines = f.read().splitlines()
    except OSError as e:
        log.warning("no se pueden leer los montajes del host: %s", e)
        return []
    out, seen = [], set()
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        src, mp, fstype = _unescape(parts[0]), _unescape(parts[1]), parts[2]
        if fstype not in FS_TYPES or mp in ignored:
            continue
        if fstype == "zfs" and "/" in src:      # solo el dataset raíz de cada pool
            continue
        if src in seen or mp.startswith(("/var/lib/docker", "/snap", "/run")):
            continue
        seen.add(src)
        try:
            st = os.statvfs(f"{HOST_PROC}/root{mp}")
        except OSError:
            continue
        total = st.f_blocks * st.f_frsize
        if total == 0:
            continue
        free = st.f_bavail * st.f_frsize
        used = total - st.f_bfree * st.f_frsize
        out.append({"mount": mp, "source": src, "fstype": fstype, "total": total, "used": used,
                    "avail": free, "pct": round(used / (used + free) * 100, 1) if used + free else 0,
                    "disk": _base_disk(src) if src.startswith("/dev/") else None})
    return sorted(out, key=lambda x: x["mount"])


# ---------------------------------------------------------------- scrubs programados por el sistema

def host_scrub_jobs() -> list[dict]:
    """Scrubs que el propio servidor ya programa (cron / timers de systemd), para avisar si se duplican."""
    root = f"{HOST_PROC}/root"
    out = []
    files = []
    try:   # sin pid: host, /proc/1 es el propio contenedor: no hay nada del host que leer
        if os.readlink(f"{HOST_PROC}/ns/pid") == os.readlink("/proc/self/ns/pid"):
            return []
    except OSError:
        return []
    for d in ("/etc/cron.d", "/etc/cron.weekly", "/etc/cron.monthly", "/etc/cron.daily"):
        try:
            files += [f"{d}/{f}" for f in sorted(os.listdir(root + d))]
        except OSError:
            pass
    files.append("/etc/crontab")
    for f in files:
        try:
            with open(root + f, errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        for line in lines:
            ln = line.strip()
            if not ln or ln.startswith("#") or not re.search(r"zpool\s+scrub|zfs-linux/scrub|zfs-scrub", ln):
                continue
            parts = ln.split()
            expr = " ".join(parts[:5]) if len(parts) > 5 and f.startswith("/etc/cron.d") or f == "/etc/crontab" else None
            note = ""
            if expr:
                p = expr.split()
                if p[2] != "*" and p[4] != "*" and "date" not in ln:
                    note = ("cron usa día del mes O día de la semana: esta línea corre ambos días, "
                            "no sólo cuando coinciden")
                elif "date +" in ln and "-eq" in ln:
                    note = "se ejecuta sólo el día de la semana que comprueba el script"
            elif "/cron." in f:
                note = f"se ejecuta {'cada semana' if 'weekly' in f else 'cada mes' if 'monthly' in f else 'cada día'}"
            out.append({"source": f, "line": ln[:200], "cron": expr, "note": note, "human": _cron_human(expr, ln)})
    for d in ("/etc/systemd/system/timers.target.wants",):
        try:
            for t in sorted(os.listdir(root + d)):
                if "scrub" in t and "zfs" in t:
                    out.append({"source": f"{d}/{t}", "line": t, "cron": None, "note": "timer de systemd activo"})
        except OSError:
            pass
    return out


def _cron_human(expr: str | None, line: str) -> str:
    from .schedule import DOW, DOW_PL, NTH, describe, from_cron
    if not expr:
        return ""
    mi, ho, dom, mon, dow = expr.split()
    if not (mi.isdigit() and ho.isdigit()) or mon != "*":
        return ""
    at = f"a las {int(ho):02d}:{int(mi):02d}"
    weeks = {"1-7": 1, "8-14": 2, "15-21": 3, "22-28": 4}
    if dom in weeks and dow == "*" and (m := re.search(r"date \+\\?%w\)?\s*\]?\s*-eq\s*([0-6])|%w\)\" -eq ([0-6])|-eq ([0-6])", line)):
        d = int(next(g for g in m.groups() if g is not None))
        return f"El {NTH[weeks[dom]]} {DOW[d]} de cada mes {at}"
    if dom.isdigit() and dow.isdigit() and 0 <= int(dow) <= 6:
        return f"Todos los {DOW_PL[int(dow)]} y además el día {dom} de cada mes, {at}"
    w = from_cron(expr)
    return describe(w) if w.get("freq") != "cron" else ""
