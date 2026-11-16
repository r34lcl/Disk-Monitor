"""Envío de avisos.

Un mensaje es {title, severity, lead?, sections:[{heading, items:[item]}], footer?, link?}
con item = {emoji, name?, text, detail?, hint?, ident?}:
  name   → se destaca en negrita (p.ej. "sda")
  detail → explicación corta
  hint   → qué hacer (👉)
  ident  → modelo y serie para ubicar el disco físico
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import smtplib
import ssl
import time
from email.message import EmailMessage

import httpx

from .i18n import _

log = logging.getLogger("disk-monitor")
RETRY_DELAYS = [5, 20, 60]
SEV_EMOJI = {"critical": "🔴", "warning": "🟡", "info": "🔵", "ok": "✅"}
SEV_COLOR = {"critical": "#d03b3b", "warning": "#c98a00", "info": "#2563eb", "ok": "#0c8a0c"}


def _esc(s) -> str:
    return html.escape(str(s or ""), quote=False)


def _head(it: dict) -> str:
    return (f"{it['name']} " if it.get("name") else "") + it["text"]


def telegram_html(msg: dict, limit: int = 4096) -> str:
    out = [f"{SEV_EMOJI.get(msg['severity'], '💽')} <b>{_esc(msg['title'])}</b>"]
    if msg.get("lead"):
        out.append(_esc(msg["lead"]))
    for sec in msg["sections"]:
        out.append("")
        if sec.get("heading"):
            out.append(f"<b>{_esc(sec['heading'])}</b>")
        for it in sec["items"]:
            name = f"<b>{_esc(it['name'])}</b> " if it.get("name") else ""
            out.append(f"{it.get('emoji', '•')} {name}{_esc(it['text'])}")
            if it.get("detail"):
                out.append(f"      {_esc(it['detail'])}")
            if it.get("hint"):
                out.append(f"      👉 {_esc(it['hint'])}")
            if it.get("ident"):
                out.append(f"      <i>{_esc(it['ident'])}</i>")
    tail = []
    if msg.get("footer"):
        tail.append(f"<i>{_esc(msg['footer'])}</i>")
    if msg.get("link"):
        tail.append(f'<a href="{_esc(msg["link"])}">{_("Abrir Disk Monitor")}</a>')
    if tail:
        out += [""] + tail
    txt = "\n".join(out)
    return txt if len(txt) <= limit else txt[: limit - 20] + "\n…" + _("(recortado)")


def plain_text(msg: dict) -> str:
    out = [f"{SEV_EMOJI.get(msg['severity'], '')} {msg['title']}".strip()]
    if msg.get("lead"):
        out.append(msg["lead"])
    for sec in msg["sections"]:
        out.append("")
        if sec.get("heading"):
            out.append(sec["heading"])
        for it in sec["items"]:
            out.append(f"{it.get('emoji', '-')} {_head(it)}")
            for k, pre in (("detail", ""), ("hint", "👉 "), ("ident", "")):
                if it.get(k):
                    out.append(f"      {pre}{it[k]}")
    if msg.get("footer") or msg.get("link"):
        out.append("")
    if msg.get("footer"):
        out.append(msg["footer"])
    if msg.get("link"):
        out.append(msg["link"])
    return "\n".join(out)


def markdown(msg: dict) -> str:
    out = [msg["lead"], ""] if msg.get("lead") else []
    for sec in msg["sections"]:
        if sec.get("heading"):
            out.append(f"**{sec['heading']}**")
        for it in sec["items"]:
            name = f"**{it['name']}** " if it.get("name") else ""
            out.append(f"- {it.get('emoji', '')} {name}{it['text']}")
            if it.get("detail"):
                out.append(f"  {it['detail']}")
            if it.get("hint"):
                out.append(f"  👉 {it['hint']}")
            if it.get("ident"):
                out.append(f"  _{it['ident']}_")
        out.append("")
    if msg.get("footer"):
        out.append(f"_{msg['footer']}_")
    if msg.get("link"):
        out.append(msg["link"])
    return "\n".join(out)


def email_html(msg: dict) -> str:
    color = SEV_COLOR.get(msg["severity"], "#2563eb")
    rows = []
    for sec in msg["sections"]:
        if sec.get("heading"):
            rows.append(f'<tr><td style="padding:18px 0 6px;font-weight:600;font-size:13px;color:#5b677a;'
                        f'text-transform:uppercase;letter-spacing:.04em">{_esc(sec["heading"])}</td></tr>')
        for it in sec["items"]:
            name = f"<b>{_esc(it['name'])}</b> " if it.get("name") else ""
            extra = ""
            if it.get("detail"):
                extra += f'<div style="color:#334155;font-size:13px;margin-top:3px">{_esc(it["detail"])}</div>'
            if it.get("hint"):
                extra += (f'<div style="margin-top:6px;padding:6px 9px;background:#f1f5f9;border-radius:6px;'
                          f'font-size:13px">👉 {_esc(it["hint"])}</div>')
            if it.get("ident"):
                extra += f'<div style="color:#5b677a;font-size:12px;margin-top:4px">{_esc(it["ident"])}</div>'
            rows.append(f'<tr><td style="padding:8px 0;border-bottom:1px solid #e6ebf1">{it.get("emoji", "")} '
                        f'{name}{_esc(it["text"])}{extra}</td></tr>')
    lead = f'<p style="margin:8px 0 0;color:#334155">{_esc(msg["lead"])}</p>' if msg.get("lead") else ""
    link = (f'<p style="margin-top:20px"><a href="{_esc(msg["link"])}" style="background:{color};color:#fff;'
            f'padding:9px 16px;border-radius:6px;text-decoration:none">{_("Abrir Disk Monitor")}</a></p>') if msg.get("link") else ""
    foot = _esc(msg.get("footer") or time.strftime("%d-%m-%Y %H:%M"))
    return (f'<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:640px;margin:auto;color:#0f172a">'
            f'<div style="border-top:4px solid {color};padding:16px 0 4px"><h2 style="margin:0;font-size:19px">'
            f'{SEV_EMOJI.get(msg["severity"], "")} {_esc(msg["title"])}</h2>{lead}</div>'
            f'<table style="width:100%;border-collapse:collapse;font-size:14px">{"".join(rows)}</table>{link}'
            f'<p style="color:#5b677a;font-size:12px;margin-top:18px">{foot}</p></div>')


async def send_telegram(cfg: dict, msg: dict) -> list[dict]:
    token = (cfg.get("bot_token") or "").strip()
    chats = [c.strip() for c in str(cfg.get("chat_ids", "")).replace(";", ",").split(",") if c.strip()]
    if not token or not chats:
        return [{"channel": "telegram", "ok": False, "error": "falta bot_token o chat_ids"}]
    out = []
    silent = bool(cfg.get("silent_warnings")) and msg["severity"] != "critical"
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=60)) as c:
        for chat in chats:
            data = {"chat_id": chat, "parse_mode": "HTML", "text": telegram_html(msg),
                    "disable_notification": str(silent).lower(),
                    "link_preview_options": json.dumps({"is_disabled": True})}
            err = None
            for attempt, wait in enumerate(RETRY_DELAYS + [None]):
                try:
                    r = await c.post(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
                    j = r.json()
                    if j.get("ok"):
                        err = None
                        break
                    err = j.get("description") or f"HTTP {r.status_code}"
                    if r.status_code == 429:
                        wait = int((j.get("parameters") or {}).get("retry_after") or wait or 5)
                    elif r.status_code < 500:
                        break
                except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError) as e:
                    err = f"{type(e).__name__}: sin respuesta (no se reintenta para no duplicar)"
                    break
                except httpx.TransportError as e:
                    err = f"{type(e).__name__}: {e}" or type(e).__name__
                except Exception as e:  # noqa: BLE001
                    err = f"{type(e).__name__}: {e}"
                    break
                if wait is None:
                    break
                log.warning("telegram %s: %s — reintento %d en %ds", chat, err, attempt + 1, wait)
                await asyncio.sleep(wait)
            out.append({"channel": "telegram", "target": chat, "ok": err is None, "error": err})
    return out


def _send_email_sync(cfg: dict, msg: dict) -> list[dict]:
    to = [t.strip() for t in str(cfg.get("to", "")).replace(";", ",").split(",") if t.strip()]
    if not cfg.get("host"):
        return [{"channel": "email", "ok": False, "error": "falta el servidor SMTP"}]
    if not to:
        return [{"channel": "email", "ok": False, "error": "faltan destinatarios"}]
    em = EmailMessage()
    em["Subject"] = f"{SEV_EMOJI.get(msg['severity'], '')} {msg['title']}"
    em["From"] = cfg.get("from") or cfg.get("username")
    em["To"] = ", ".join(to)
    em.set_content(plain_text(msg))
    em.add_alternative(email_html(msg), subtype="html")
    port = int(cfg.get("port") or 587)
    sec = cfg.get("security", "starttls")
    err = None
    for attempt, wait in enumerate(RETRY_DELAYS + [None]):
        try:
            if sec == "ssl":
                s = smtplib.SMTP_SSL(cfg["host"], port, context=ssl.create_default_context(), timeout=30)
            else:
                s = smtplib.SMTP(cfg["host"], port, timeout=30)
                if sec == "starttls":
                    s.starttls(context=ssl.create_default_context())
            with s:
                if cfg.get("username"):
                    s.login(cfg["username"], cfg.get("password", ""))
                s.send_message(em)
            err = None
            break
        except smtplib.SMTPAuthenticationError as e:
            err = f"login SMTP: {e}"
            break
        except (OSError, smtplib.SMTPException) as e:
            err = f"SMTP: {e}"
            if wait is None:
                break
            log.warning("SMTP: %s — reintento %d en %ds", e, attempt + 1, wait)
            time.sleep(wait)
    return [{"channel": "email", "target": ", ".join(to), "ok": err is None, "error": err}]


def _send_apprise_sync(cfg: dict, msg: dict) -> list[dict]:
    import apprise
    urls = [u.strip() for u in (cfg.get("urls") or "").splitlines() if u.strip() and not u.strip().startswith("#")]
    if not urls:
        return [{"channel": "apprise", "ok": False, "error": "sin URLs"}]
    ntype = {"critical": apprise.NotifyType.FAILURE, "warning": apprise.NotifyType.WARNING,
             "ok": apprise.NotifyType.SUCCESS}.get(msg["severity"], apprise.NotifyType.INFO)
    out = []
    for u in urls:
        a = apprise.Apprise()
        scheme = u.split("://")[0]
        if not a.add(u):
            out.append({"channel": "apprise", "target": scheme, "ok": False, "error": "URL inválida"})
            continue
        ok = a.notify(title=msg["title"], body=markdown(msg), body_format=apprise.NotifyFormat.MARKDOWN,
                      notify_type=ntype)
        out.append({"channel": "apprise", "target": scheme, "ok": bool(ok), "error": None if ok else "falló el envío"})
    return out


async def dispatch(settings: dict, msg: dict, only: str | None = None) -> list[dict]:
    jobs = []
    for name in ("telegram", "email", "apprise"):
        cfg = settings[name]
        if (only and only == name) or (not only and cfg.get("enabled")):
            if name == "telegram":
                jobs.append(send_telegram(cfg, msg))
            elif name == "email":
                jobs.append(asyncio.to_thread(_send_email_sync, cfg, msg))
            else:
                jobs.append(asyncio.to_thread(_send_apprise_sync, cfg, msg))
    results = []
    for r in await asyncio.gather(*jobs, return_exceptions=True):
        if isinstance(r, Exception):
            results.append({"channel": "?", "ok": False, "error": f"{type(r).__name__}: {r}"})
        else:
            results.extend(r)
    return results
