# Disk Monitor

**English** · [Español](README.es.md)

Version 1.2 · [KqK.cl](https://kqk.cl)

Self-hosted web dashboard that watches the **physical disks** of a Linux server and notifies you when something goes wrong.

- **SMART** status of every disk: health, temperature, power-on hours, reallocated/pending sectors, CRC errors, SSD/NVMe wear, SMART tests.
- **ZFS pool** status (if any): health, per-vdev errors, usage and scrub progress; scrubs can be started, paused or stopped from the dashboard.
- **Space** on mounted file systems.
- **Automatic disk detection**: at startup, on demand and with a periodic probe; notifies about new or missing disks.
- **Scheduled tasks** with simple schedules (every N minutes, daily, certain weekdays, once a month, "the 2nd Sunday"…): disk check, **SMART tests**, **ZFS scrub** and status summary. Each one has an on/off switch and can be run right away.
- **Clear notifications**: what happened, what it means and what to do, with the disk's model and serial number so you can find it. Via Telegram, email (SMTP) and 100+ services through [Apprise](https://github.com/caronc/apprise) (Discord, Slack, ntfy, Pushover, Gotify, Matrix, Teams…).
- Temperature, alert and notification history.
- Interface and notifications in **English or Spanish**.

Everything runs in a single Docker container; the host doesn't need `smartmontools` or anything else installed.

---

## Contents

1. [Requirements](#1-requirements)
2. [Quick install](#2-quick-install)
3. [Manual install, step by step](#3-manual-install-step-by-step)
4. [First login and checks](#4-first-login-and-checks)
5. [Setting up notifications](#5-setting-up-notifications)
6. [General settings](#6-general-settings)
7. [Publishing it on a domain (reverse proxy)](#7-publishing-it-on-a-domain-reverse-proxy)
8. [Installing on several servers](#8-installing-on-several-servers)
9. [Maintenance](#9-maintenance)
10. [Troubleshooting](#10-troubleshooting)
11. [Security](#11-security)
12. [Reference](#12-reference)
- [License](#license)

---

## 1. Requirements

| Requirement | Details |
|---|---|
| System | Linux x86_64 with access to the physical disks (bare metal, or a VM with the disks/HBA passed through) |
| Docker | Docker Engine 20.10+ with the **Compose** plugin (`docker compose`) or `docker-compose` |
| Permissions | Able to run `docker` (root or a user in the `docker` group) |
| Port | One free port for the web UI (**8093** by default) |
| Network | Internet access only to send notifications (Telegram, SMTP, etc.) and to build the image |
| Git | To download and update (`apt install git`). Without git you can use the GitHub ZIP (needs `unzip`) |

Check Docker:

```sh
docker --version
docker compose version     # or: docker-compose --version
```

If you don't have it, on Debian/Ubuntu: `curl -fsSL https://get.docker.com | sh`

**Supported hardware**: SATA and SAS disks (direct or behind an HBA), NVMe, disks behind hardware RAID controllers (MegaRAID/LSI, HP Smart Array `cciss`, Areca…) and USB disks with a compatible bridge. Devices that don't report SMART (VM virtual disks, some USB enclosures) show up as "No SMART" and only their presence is monitored.

---

## 2. Quick install

Clone the repository and run the installer:

```sh
git clone https://github.com/r34lcl/Disk-Monitor.git disk-monitor
cd disk-monitor
./install.sh
```

**Without git**, using the GitHub ZIP (the same one as **Code → Download ZIP**). It extracts to `Disk-Monitor-main`, so rename the folder:

```sh
wget https://github.com/r34lcl/Disk-Monitor/archive/refs/heads/main.zip          # or: curl -LO https://github.com/r34lcl/Disk-Monitor/archive/refs/heads/main.zip
unzip main.zip && mv Disk-Monitor-main disk-monitor
cd disk-monitor
sh install.sh
```

The script:

1. Checks that Docker and Compose are available.
2. Creates the `data/` folder and, if missing, an `.env` file with user `admin` and a **random password**.
3. Builds the image and starts the container.
4. Prints the URL and the credentials.

To use another port: `HOST_PORT=9000 ./install.sh`

The initial language follows the system `LANG` (English if it starts with `en`, otherwise Spanish). To force it: `APP_LANG=en ./install.sh`. It can be changed later from the web UI.

Then continue with [section 4](#4-first-login-and-checks).

---

## 3. Manual install, step by step

If you'd rather not use the script:

**3.1. Download the code** (in the folder where you want it installed)

```sh
git clone https://github.com/r34lcl/Disk-Monitor.git disk-monitor
cd disk-monitor
mkdir -p data
```

Expected layout:

```
disk-monitor/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── VERSION
├── install.sh
├── app/            (code)
└── data/           (database; created automatically)
```

**3.2. Create the `.env` file**

```sh
cat > .env <<'EOF'
APP_USER=admin
APP_PASSWORD=put-a-long-password-here
HOST_PORT=8093
TZ=America/New_York
APP_LANG=en
EOF
chmod 600 .env
```

| Variable | Purpose |
|---|---|
| `APP_USER` / `APP_PASSWORD` | Web UI login. `APP_PASSWORD` is required: if it's empty, the web UI won't open and shows how to set it. To run without a password (only on a trusted network) add `AUTH_DISABLED=1`. |
| `HOST_PORT` | Host port where the web UI is published. |
| `APP_LANG` | Initial language of the web UI and notifications: `es` (default) or `en`. Only used on first install; afterwards change it from the web UI. |
| `TZ` | Time zone for scheduled tasks and dates ([list](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)). Defaults to `UTC`. |

Generate a password with: `head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 18`

**3.3. Build and start**

```sh
docker compose up -d --build
```

**3.4. Check that it started**

```sh
docker compose ps
docker compose logs --tail 20
```

You should see lines like these (the logs are in Spanish):

```
INFO inventario inicial: 4 discos (sda, sdb, sdc, nvme0)
INFO revisión (inicio) en 1.2s: 4 discos, 0 problemas, 0 eventos
```

---

## 4. First login and checks

1. Open `http://SERVER-IP:8093` and log in with the user and password from `.env`.
2. On the **Dashboard**, check that all your disks are listed. Below the top bar you'll see the smartctl version and where ZFS is read from.
3. Press **Detect disks** to see the inventory: present, standby or missing disks.
4. Click a disk to see its details: full SMART attributes, temperature chart, SMART tests and alerts. From there you can run a **short test** to confirm everything works.

If a disk is missing, see [section 10](#10-troubleshooting).

---

## 5. Setting up notifications

Everything is configured in the **Settings** tab and saved with **Save**. Each channel has a **Send test** button.

### Telegram

1. In Telegram, talk to **@BotFather**, send `/newbot` and follow the steps. Copy the **token** (`123456789:ABC...`).
2. Get your **chat ID**:
   - Private chat: send anything to your bot and open
     `https://api.telegram.org/bot<TOKEN>/getUpdates`; the number in `"chat":{"id":...}` is your chat ID.
   - Group: add the bot to the group, send a message and use the same URL; the ID starts with `-100`.
3. In Settings → Telegram: tick **Enabled**, paste the token and chat ID(s) (several separated by commas) and press **Send test**.

**Silent warnings** option: 🟡 warnings arrive without sound; critical ones always make a sound.

### Email (SMTP)

| Provider | Server | Port | Security |
|---|---|---|---|
| Gmail | `smtp.gmail.com` | 587 | STARTTLS (needs an [app password](https://myaccount.google.com/apppasswords)) |
| Outlook / Microsoft 365 | `smtp.office365.com` | 587 | STARTTLS |
| Your own server | yours | 465 / 587 / 25 | SSL / STARTTLS / none |

Fill in username, password, sender (optional) and recipients separated by commas.

### Other services (Apprise)

One URL per line. Examples:

```
discord://WEBHOOK_ID/WEBHOOK_TOKEN
ntfy://ntfy.sh/my-secret-topic
pover://USER_KEY@APP_TOKEN
slack://TokenA/TokenB/TokenC
gotify://my-server/TOKEN
mailto://user:password@gmail.com
```

Formats for every service: <https://github.com/caronc/apprise/wiki>

### How notifications behave

- **Problems** (conditions that persist, like high temperature or a degraded pool): you're notified when they appear, when they get worse, with a **reminder** every N hours while they last (configurable; 0 = never) and when they're **resolved**.
- **Events** (one-off changes, like a sector counter going up, new CRC errors, a new disk, a finished SMART test or scrub): notified once.
- Every problem comes with a 👉 line saying **what to do** and, for disks, the **model and serial number** so you can find it in the case.
- Each check sends **a single message** with everything new, not one per problem.
- **Notify from**: choose warnings 🟡 and critical 🔴, or critical only.
- An active alert can be **Muted** (stops reminders; you're notified again if it gets worse).
- **Status summary** (optional task): sends the status of all disks, pools and space, plus upcoming tasks, even when there are no problems.
- **SMART tests and scrubs**: if they finish with errors you're always notified; if they pass, it depends on each task's "Also notify when it finishes without problems" option. Scrubs also notify **when they start**, with an estimated finish time based on the previous run. Scrubs started outside Disk Monitor (e.g. by the system cron) are detected too and notified when they start and finish (Settings → Alerts).
- **ZFS is checked every 5 minutes** (`zpool status`, which doesn't wake disks): if a pool degrades or read, write or checksum errors show up, you're notified right away without waiting for the next full check.

---

## 6. General settings

| Section | Options |
|---|---|
| Alerts | Minimum severity, reminders, resolved notifications, new disks, tests and scrubs started outside the tasks. |
| Thresholds | HDD and SSD temperature, sectors, SSD wear, NVMe spare, disk/pool usage and max days without a ZFS scrub. |
| General | **Language** (English / Spanish) of the web UI and notifications, server name in notifications, public URL (for the link in messages), history retention, mounts to ignore, settings export/import. |

The language can also be changed with the **ES | EN** selector next to the title, top left. It applies to the web UI and to notifications sent from then on (active problems are reworded on the next check, which runs automatically when you switch).

### Scheduled tasks (Tasks tab)

Each task has an on/off switch, its schedule in plain words ("Wednesdays at 04:00"), the next run, the result of the last one and a **Run now** button. **Edit** changes the schedule without writing cron:

| Repeat | Example |
|---|---|
| At an interval | every 30 minutes, every 6 hours |
| Every day | at 01:00 |
| Certain weekdays | Monday, Wednesday and Friday at 04:00 |
| Once a month (fixed day) | on the 1st at 01:00 |
| Once a month (e.g. 2nd Sunday) | the second Sunday at 02:00 |
| Advanced (cron) | `0 9 * * 1-5` |

While editing, the next three runs are shown. Times are in the server's time zone (`TZ` in `.env`).

| Task | What it does | Default |
|---|---|---|
| Disk check | Reads SMART, ZFS and space; notifies if there are problems. | every 30 min |
| Short SMART test | 1–2 min self-test, without affecting normal use. | Wednesday 04:00 |
| Long SMART test | Reads the whole surface; on large disks it takes hours (12 TB ≈ 18–23 h). | disabled, 1st at 01:00 |
| ZFS scrub | ZFS verifies and repairs all the data in the pool. Not started if the pool is degraded or a scrub/resilver is already running. | disabled, 2nd Sunday 02:00 |
| Status summary | Sends the full status through the notification channels. | disabled, Monday 09:00 |

**Servers without ZFS**: Disk Monitor detects pools by itself (on every check). If there are none, the pools section isn't shown, the **+ ZFS scrub** button is hidden and an existing scrub task (e.g. imported from another server) becomes **inactive** without errors; if a pool is created later, it starts working on its own.

**+ SMART test**, **+ ZFS scrub** and **+ Summary** add more tasks (for example, a long test for certain disks only). If a scrub and a long test fall within 24 h of each other, the tab warns you.

**System scrubs**: many distributions already schedule a monthly scrub (Ubuntu/Debian: `/etc/cron.d/zfsutils-linux`). Disk Monitor detects them, shows them in the Tasks tab with their schedule in plain words and notifies when they finish. If you'd rather manage them from Disk Monitor, enable the **ZFS scrub** task and disable the system ones with the command shown in the tab.

> The **long test** and the **scrub** are heavy: schedule them at quiet hours, apart from each other and from your backups.

**Ignoring a disk**: in its details, **Ignore alerts for this disk**. It stays on the dashboard but doesn't generate notifications.

---

## 7. Publishing it on a domain (reverse proxy)

The app speaks HTTP on the configured port. For HTTPS and a domain, put a reverse proxy in front of it:

- **Nginx Proxy Manager / Traefik / Caddy**: create a host pointing to `http://SERVER-IP:8093`.
- **Nginx** by hand:

  ```nginx
  location / {
      proxy_pass http://127.0.0.1:8093;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
  }
  ```

With `X-Forwarded-Proto: https` the session cookie is marked secure. Then set the public URL in Settings → General so notifications include the link.

If you'll only use it behind the proxy, you can publish the port on localhost only by changing the `ports` line in `docker-compose.yml` to `"127.0.0.1:${HOST_PORT:-8093}:8000"`.

---

## 8. Installing on several servers

Clone the repository on each server following [section 2](#2-quick-install). Each install is independent and detects its own disks at startup.

**Copying settings** (channels, thresholds, schedules) from one server to another:

1. On the source server: Settings → General → **Export settings**. Use **Export without passwords** if the file will be passed around.
2. On the new one: Settings → General → **Import…**

The server name, URL and ignored disks are not copied, since they belong to each machine. If you import an export without passwords, the destination keeps the ones it already has.

Give each one a different **server name** (Settings → General) to tell where each notification comes from; the hostname is used by default.

---

## 9. Maintenance

| Task | Command (inside the `disk-monitor` folder) |
|---|---|
| View logs | `docker compose logs -f` |
| Restart | `docker compose restart` |
| Apply `.env` changes | `docker compose up -d` (`restart` does **not** reload the variables) |
| Update to a new version | `git pull && ./install.sh` (`data/` and `.env` are kept; git doesn't touch them). If you installed from the ZIP: download the new one, extract it and copy its contents over the folder (`unzip -o main.zip && cp -r Disk-Monitor-main/. disk-monitor/`), then `cd disk-monitor && sh install.sh`. Schedules from older versions are converted to tasks automatically. |
| Stop | `docker compose down` |
| Back up | copy `data/disk-monitor.db` and `.env` |
| Change the password | edit `APP_PASSWORD` in `.env`, then `docker compose up -d` (logs out open sessions) |
| Uninstall | `docker compose down --rmi local` and delete the folder |

History is pruned automatically according to the configured retention (120 days by default).

---

## 10. Troubleshooting

**No disks show up / "can't read SMART"**
- The container must run with `privileged: true` and `/dev` mounted (already set in `docker-compose.yml`).
- In a VM, virtual disks have no SMART: pass the disk or the whole HBA through to the VM, or install Disk Monitor on the hypervisor.
- Check from inside the container:
  ```sh
  docker exec disk-monitor smartctl --scan-open
  docker exec disk-monitor smartctl -x /dev/sda
  ```

**Disks behind a RAID controller don't show up**
`smartctl --scan-open` detects MegaRAID/cciss/Areca automatically. If your controller doesn't show up, its firmware may not expose SMART through the array; check the smartctl documentation for your model (`-d megaraid,N`, `-d cciss,N`, etc.).

**A disk shows as "Standby"**
It's spun down and, with the "Don't wake sleeping disks" option, its last reading is shown. Turn the option off if you'd rather always read it (it will wake it on every check).

**ZFS doesn't show up**
It's only shown if the host has the ZFS module loaded (`/dev/zfs`). The dashboard shows whether the host's or the container's `zpool` is used. To check: `docker exec disk-monitor zpool status`.

**Notifications don't arrive**
- Use **Send test** on each channel; the result and the error are shown on screen.
- The **Activity** tab has the details of every send.
- Check that the server has internet access and DNS from Docker: `docker exec disk-monitor getent hosts api.telegram.org`

**Task times are off**
Set `TZ` in `.env` and apply with `docker compose up -d`.

**The port is in use**
Change `HOST_PORT` in `.env` and run `docker compose up -d`.

---

## 11. Security

- The container is **privileged** (full access to the host hardware). Treat the web UI as an admin panel: strong password and no direct exposure to the internet. Use a reverse proxy with HTTPS, a VPN, or publish the port on the internal network only.
- Login blocks an IP for 15 minutes after 10 failed attempts.
- Telegram and SMTP passwords are stored in `data/disk-monitor.db` and the web UI never shows them (they appear masked). Protect that folder and `.env` (`chmod 600 .env`).
- The settings export **includes** secrets, unless you use "Export without passwords".

---

## 12. Reference

**What it detects**

| Source | Severity | Condition |
|---|---|---|
| SMART | 🔴 | The disk reports FAILED, or a pre-fail attribute is below its threshold |
| SMART | 🔴 | Pending or uncorrectable sectors; the last SMART test failed |
| SMART | 🟡 / 🔴 | Reallocated sectors (warning and critical thresholds) |
| SMART | 🟡 / 🔴 | Temperature (separate thresholds for HDD and SSD/NVMe) |
| SSD/NVMe | 🟡 / 🔴 | Wear, available spare, `critical_warning`, media errors |
| SAS | 🟡 / 🔴 | Grown defect list, uncorrected I/O errors |
| Events | 🟡 | A counter goes up: reallocated, pending, CRC, error log, bad blocks… |
| Inventory | 🔴 / 🔵 | A known disk disappears / a new disk shows up |
| ZFS | 🔴 | Pool not ONLINE (including DEGRADED) or data errors |
| ZFS | 🟡 | Read/write/checksum errors on vdevs, errors in the last scrub, old scrub |
| Space | 🟡 / 🔴 | File system or pool above the usage threshold |

**Why the container needs privileges**

| Option | Reason |
|---|---|
| `privileged: true` | `smartctl` sends commands directly to the disks and controllers. |
| `/dev:/dev` | Access to `/dev/sdX`, `/dev/nvmeX`, `/dev/zfs` and `/dev/disk/by-id`. |
| `pid: host` | Read the host's mounts and free space (`/proc/1`) and use its `zpool` (`nsenter`). |
| `/run/udev` (read-only) | udev data to identify models and serial numbers. Harmless if it doesn't exist on the host. |

**API** (for scripts and external monitoring; accepts Basic Auth with the `.env` credentials):

| Method | Path | Use |
|---|---|---|
| GET | `/health` | No authentication. Returns `{"ok": true, "version": "1.2", "last_check": <epoch>, "language": "en"}` |
| GET | `/api/status` | Full status: disks, pools, file systems and active alerts |
| GET | `/api/inventory` | Disk inventory (present and missing) |
| POST | `/api/check` | Run a check |
| POST | `/api/discover` | Detect disks and check |
| POST | `/api/selftest` | `{"type": "short"\|"long", "disks": [keys]}` |
| GET | `/api/tasks` | Scheduled tasks with next and last run |
| POST | `/api/tasks/{id}/run` | Run a task now (`check`, `smart-short`, `scrub`, `report`…) |
| POST | `/api/zfs/{pool}/scrub` | `{"action": "start"\|"pause"\|"stop"}` |
| GET | `/api/alerts` | Alert history |

Example: `curl -u admin:PASSWORD -X POST http://localhost:8093/api/check`

**Files**

| Path | Contents |
|---|---|
| `.env` | Credentials, port, time zone and initial language |
| `data/disk-monitor.db` | SQLite database: settings, inventory, history, alerts and notifications |
| `install.sh` | Install or update |
| `VERSION` | Installed version (shown at the bottom of the web UI) |

---

## License

Disk Monitor is free software under the [Apache License 2.0](LICENSE). You may use, modify, fork and redistribute it, including for commercial purposes, as long as you:

- keep the `LICENSE` and `NOTICE` files in your copy or derived version, with credit to the original project: **Disk Monitor by [KqK.cl](https://kqk.cl)** — <https://github.com/r34lcl/Disk-Monitor>;
- state in the files you modify that they were changed.

It is provided "as is", without warranty. See the full text in `LICENSE`.
