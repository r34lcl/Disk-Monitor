# Disk Monitor

[English](README.md) · **Español**

Versión 1.2.3 · [KqK.cl](https://kqk.cl)

Panel web autoalojado que vigila los **discos físicos** de un servidor Linux y avisa cuando algo anda mal.

- Estado **SMART** de cada disco: salud, temperatura, horas de uso, sectores reasignados/pendientes, errores CRC, desgaste de SSD/NVMe, pruebas SMART.
- Estado de **pools ZFS** (si existen): salud, errores por vdev, ocupación y avance del scrub; se puede iniciar, pausar o detener un scrub desde el panel.
- **Espacio** de los sistemas de archivos montados.
- **Detección automática de discos**: al iniciar, bajo demanda y con un sondeo periódico; avisa de discos nuevos o que desaparecen.
- **Tareas programadas** con horarios simples (cada N minutos, a diario, ciertos días, una vez al mes, «el 2º domingo»…): revisión de discos, **pruebas SMART**, **scrub de ZFS** y resumen del estado. Cada una se activa con un interruptor y se puede ejecutar al instante.
- **Avisos claros**: qué pasó, qué significa y qué hacer, con modelo y serie del disco para ubicarlo. Por Telegram, correo (SMTP) y más de 100 servicios vía [Apprise](https://github.com/caronc/apprise) (Discord, Slack, ntfy, Pushover, Gotify, Matrix, Teams…).
- Historial de temperaturas, alertas y avisos enviados.

Todo corre en un único contenedor Docker; el host no necesita tener instalado `smartmontools` ni nada más.

---

## Capturas

![Panel](docs/screenshots/es-dashboard.png)

<details>
<summary>Más capturas (detalle de disco, tareas, alertas, actividad, configuración)</summary>

<table>
<tr><td width="50%" align="center"><a href="docs/screenshots/es-disk-detail.png"><img src="docs/screenshots/es-disk-detail.png" alt="Detalle de un disco: historial de temperatura y atributos SMART"></a><br><sub>Detalle de un disco: historial de temperatura y atributos SMART</sub></td><td width="50%" align="center"><a href="docs/screenshots/es-tasks.png"><img src="docs/screenshots/es-tasks.png" alt="Tareas programadas"></a><br><sub>Tareas programadas</sub></td></tr>
<tr><td width="50%" align="center"><a href="docs/screenshots/es-alerts.png"><img src="docs/screenshots/es-alerts.png" alt="Alertas"></a><br><sub>Alertas</sub></td><td width="50%" align="center"><a href="docs/screenshots/es-activity.png"><img src="docs/screenshots/es-activity.png" alt="Actividad: avisos enviados y revisiones"></a><br><sub>Actividad: avisos enviados y revisiones</sub></td></tr>
<tr><td width="50%" align="center"><a href="docs/screenshots/es-settings.png"><img src="docs/screenshots/es-settings.png" alt="Configuración: umbrales y canales de aviso"></a><br><sub>Configuración: umbrales y canales de aviso</sub></td></tr>
</table>
</details>

<sub>Tema oscuro (sigue el ajuste del sistema). Los números de serie, WWN y nombres de equipo de las capturas son ficticios.</sub>

---

## Índice

1. [Requisitos](#1-requisitos)
2. [Instalación rápida](#2-instalación-rápida)
3. [Instalación manual paso a paso](#3-instalación-manual-paso-a-paso)
4. [Primer ingreso y verificación](#4-primer-ingreso-y-verificación)
5. [Configurar las alertas](#5-configurar-las-alertas)
6. [Configuración general](#6-configuración-general)
7. [Publicarlo con un dominio (proxy inverso)](#7-publicarlo-con-un-dominio-proxy-inverso)
8. [Instalarlo en varios servidores](#8-instalarlo-en-varios-servidores)
9. [Mantenimiento](#9-mantenimiento)
10. [Solución de problemas](#10-solución-de-problemas)
11. [Seguridad](#11-seguridad)
12. [Referencia](#12-referencia)
- [Licencia](#licencia)

---

## 1. Requisitos

| Requisito | Detalle |
|---|---|
| Sistema | Linux x86_64 con acceso a los discos físicos (servidor físico, o VM con los discos/HBA pasados directamente) |
| Docker | Docker Engine 20.10+ con el plugin **Compose** (`docker compose`) o `docker-compose` |
| Permisos | Poder ejecutar `docker` (root o usuario del grupo `docker`) |
| Puerto | Uno libre para la web (por defecto **8093**) |
| Red | Salida a internet sólo para enviar avisos (Telegram, SMTP, etc.) y para construir la imagen |
| Git | Para descargar y actualizar (`apt install git`). Sin git se puede usar el ZIP de GitHub (requiere `unzip`) |

Verifica Docker:

```sh
docker --version
docker compose version     # o: docker-compose --version
```

Si no lo tienes, en Debian/Ubuntu: `curl -fsSL https://get.docker.com | sh`

**Hardware soportado**: discos SATA y SAS (directos o tras HBA), NVMe, discos detrás de controladoras RAID por hardware (MegaRAID/LSI, HP Smart Array `cciss`, Areca…) y discos USB con puente compatible. Los dispositivos que no entregan SMART (discos virtuales de VM, algunos USB) aparecen como "Sin SMART" y sólo se vigila que sigan presentes.

---

## 2. Instalación rápida

Clona el repositorio y ejecuta el instalador:

```sh
git clone https://github.com/r34lcl/Disk-Monitor.git disk-monitor
cd disk-monitor
./install.sh
```

**Sin git**, con el ZIP de GitHub (el mismo de **Code → Download ZIP**). Se descomprime en `Disk-Monitor-main`, así que hay que renombrar la carpeta:

```sh
wget https://github.com/r34lcl/Disk-Monitor/archive/refs/heads/main.zip          # o: curl -LO https://github.com/r34lcl/Disk-Monitor/archive/refs/heads/main.zip
unzip main.zip && mv Disk-Monitor-main disk-monitor
cd disk-monitor
sh install.sh
```

El script:

1. Comprueba que Docker y Compose estén disponibles.
2. Crea la carpeta `data/` y, si no existe, un archivo `.env` con usuario `admin` y una **contraseña aleatoria**.
3. Construye la imagen y levanta el contenedor.
4. Muestra la URL y las credenciales.

Para usar otro puerto: `HOST_PORT=9000 ./install.sh`

El idioma inicial sigue el `LANG` del sistema (inglés si empieza con `en`; si no, español). Para forzarlo: `APP_LANG=es ./install.sh`. Después se cambia desde la web.

Luego sigue en la [sección 4](#4-primer-ingreso-y-verificación).

---

## 3. Instalación manual paso a paso

Si prefieres no usar el script:

**3.1. Descargar el código** (en la carpeta donde quieras instalarlo)

```sh
git clone https://github.com/r34lcl/Disk-Monitor.git disk-monitor
cd disk-monitor
mkdir -p data
```

Estructura esperada:

```
disk-monitor/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── VERSION
├── install.sh
├── app/            (código)
└── data/           (base de datos; se crea sola)
```

**3.2. Crear el archivo `.env`**

```sh
cat > .env <<'EOF'
APP_USER=admin
APP_PASSWORD=pon-aqui-una-contraseña-larga
HOST_PORT=8093
TZ=America/Santiago
APP_LANG=es
EOF
chmod 600 .env
```

| Variable | Para qué sirve |
|---|---|
| `APP_USER` / `APP_PASSWORD` | Acceso a la web. `APP_PASSWORD` es obligatoria: si queda vacía, la web no abre y muestra cómo configurarla. Para usarlo sin contraseña (sólo en una red de confianza) agrega `AUTH_DISABLED=1`. |
| `HOST_PORT` | Puerto del host donde se publica la web. |
| `APP_LANG` | Idioma inicial de la web y los avisos: `es` (por defecto) o `en`. Sólo se usa en la primera instalación; después se cambia desde la web. |
| `TRUSTED_PROXIES` | IPs o redes de tu proxy inverso, separadas por comas. Sólo a ellas se les acepta `X-Forwarded-For`/`X-Forwarded-Proto` (IP real del cliente para el límite de intentos y cookie segura). Por defecto sólo loopback (`127.0.0.1/32,::1/128`). Si tu proxy entra desde otra IP (p. ej. otro equipo o la red de Docker), ponla aquí; no pongas redes enteras con clientes. |
| `COOKIE_SECURE` | `auto` (por defecto: segura si llega por HTTPS o el proxy confiable dice `https`), `1` siempre segura, `0` nunca. |
| `TZ` | Zona horaria de las tareas programadas y las fechas ([lista](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones)). Por defecto `UTC`. |

Genera una contraseña con: `head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 18`

**3.3. Construir y levantar**

```sh
docker compose up -d --build
```

**3.4. Comprobar que arrancó**

```sh
docker compose ps
docker compose logs --tail 20
```

Deberías ver una línea como:

```
INFO inventario inicial: 4 discos (sda, sdb, sdc, nvme0)
INFO revisión (inicio) en 1.2s: 4 discos, 0 problemas, 0 eventos
```

---

## 4. Primer ingreso y verificación

1. Abre `http://IP-DEL-SERVIDOR:8093` e ingresa con el usuario y contraseña del `.env`.
2. En el **Panel** revisa que aparezcan todos tus discos. Bajo la barra superior se muestra la versión de smartctl y de dónde se lee ZFS.
3. Pulsa **Detectar discos** para ver el inventario: discos presentes, en reposo o ausentes.
4. Haz clic en un disco para ver su detalle: atributos SMART completos, gráfico de temperatura, pruebas SMART y alertas. Desde ahí puedes lanzar una **prueba corta** para confirmar que todo funciona.

Si falta algún disco, revisa la [sección 10](#10-solución-de-problemas).

---

## 5. Configurar las alertas

Todo se configura en la pestaña **Configuración** y se guarda al pulsar **Guardar**. Cada canal tiene un botón **Enviar prueba**.

### Telegram

1. En Telegram habla con **@BotFather**, envía `/newbot` y sigue los pasos. Copia el **token** (`123456789:ABC...`).
2. Obtén tu **chat ID**:
   - Chat privado: escribe cualquier cosa a tu bot y abre
     `https://api.telegram.org/bot<TOKEN>/getUpdates`; el número en `"chat":{"id":...}` es tu chat ID.
   - Grupo: agrega el bot al grupo, escribe un mensaje y usa la misma URL; el ID empieza con `-100`.
3. En Configuración → Telegram: marca **Activado**, pega token y chat ID(s) (varios separados por coma) y pulsa **Enviar prueba**.

Opción **Avisos 🟡 sin sonido**: las advertencias llegan silenciosas; las críticas siempre suenan.

### Correo (SMTP)

| Proveedor | Servidor | Puerto | Seguridad |
|---|---|---|---|
| Gmail | `smtp.gmail.com` | 587 | STARTTLS (requiere [contraseña de aplicación](https://myaccount.google.com/apppasswords)) |
| Outlook / Microsoft 365 | `smtp.office365.com` | 587 | STARTTLS |
| Servidor propio | el tuyo | 465 / 587 / 25 | SSL / STARTTLS / ninguna |

Completa usuario, contraseña, remitente (opcional) y destinatarios separados por coma.

### Otros servicios (Apprise)

Una URL por línea. Ejemplos:

```
discord://ID_WEBHOOK/TOKEN_WEBHOOK
ntfy://ntfy.sh/mi-tema-secreto
pover://CLAVE_USUARIO@TOKEN_APP
slack://TokenA/TokenB/TokenC
gotify://mi-servidor/TOKEN
mailto://usuario:clave@gmail.com
```

Formatos de todos los servicios: <https://github.com/caronc/apprise/wiki>

### Cómo se comportan los avisos

- **Problemas** (condiciones que persisten, como temperatura alta o un pool degradado): se avisa al aparecer, al empeorar, con un **recordatorio** cada N horas mientras siga (configurable; 0 = nunca) y al **resolverse**.
- **Eventos** (cambios puntuales, como un contador de sectores que sube, errores CRC nuevos, un disco nuevo, una prueba SMART o un scrub terminado): se avisan una vez.
- Cada problema trae una línea 👉 con **qué hacer** y, si es de un disco, su **modelo y número de serie** para encontrarlo en el gabinete.
- Cada revisión envía **un solo mensaje** con todo lo nuevo, no uno por problema.
- **Avisar desde**: elige si quieres advertencias 🟡 y críticos 🔴, o sólo críticos.
- Una alerta activa se puede **Silenciar** (deja de enviar recordatorios; vuelve a avisar si empeora).
- **Resumen del estado** (tarea opcional): envía el estado de todos los discos, pools y espacio, más las próximas tareas, aunque no haya problemas.
- **Pruebas SMART y scrubs**: si terminan con errores siempre se avisa; si terminan bien, según la casilla «Avisar también cuando termina sin problemas» de cada tarea. El scrub avisa también **al empezar**, con la hora estimada de término según la duración del anterior. Los scrubs iniciados fuera de Disk Monitor (por ejemplo, por el cron del sistema) también se detectan y avisan al iniciar y al terminar (Configuración → Alertas).
- **ZFS se vigila cada 5 minutos** (`zpool status`, que no despierta discos): si el pool se degrada o aparecen errores de lectura, escritura o checksum, el aviso llega de inmediato, sin esperar la próxima revisión completa.

---

## 6. Configuración general

| Sección | Opciones |
|---|---|
| Alertas | Desde qué gravedad avisar, recordatorios, avisos al resolverse, discos nuevos, pruebas y scrubs iniciados fuera de las tareas. |
| Umbrales | Temperatura de HDD y SSD, sectores, desgaste de SSD, reserva de NVMe, uso de disco/pool y días máximos sin scrub de ZFS. |
| General | **Idioma** (español / inglés) de la web y los avisos, nombre del servidor en los avisos, URL pública (para el enlace en los mensajes), días de historial, montajes a ignorar, exportar/importar configuración. |

El idioma también se cambia con el selector **ES | EN** junto al título, arriba a la izquierda. Afecta a la web y a los avisos que se envíen desde ese momento (los problemas activos se vuelven a redactar en la siguiente revisión, que se lanza sola al cambiarlo).

### Tareas programadas (pestaña Tareas)

Cada tarea tiene un interruptor para activarla, su horario en palabras («Los miércoles a las 04:00»), la próxima ejecución, el resultado de la última y un botón **Ejecutar ahora**. Con **Editar** se cambia el horario sin escribir cron:

| Repetir | Ejemplo |
|---|---|
| Cada cierto tiempo | cada 30 minutos, cada 6 horas |
| Todos los días | a las 01:00 |
| Ciertos días de la semana | lunes, miércoles y viernes a las 04:00 |
| Una vez al mes (día fijo) | el día 1 a las 01:00 |
| Una vez al mes (p.ej. 2º domingo) | el segundo domingo a las 02:00 |
| Avanzado (cron) | `0 9 * * 1-5` |

Al editar se muestran las tres próximas ejecuciones. Las horas son las del servidor (`TZ` del `.env`).

| Tarea | Qué hace | Por defecto |
|---|---|---|
| Revisión de discos | Lee SMART, ZFS y espacio; avisa si hay problemas. | cada 30 min |
| Prueba SMART corta | Autodiagnóstico de 1–2 min, sin afectar el uso. | miércoles 04:00 |
| Prueba SMART larga | Lee toda la superficie; en discos grandes tarda horas (12 TB ≈ 18–23 h). | desactivada, día 1 a la 01:00 |
| Scrub ZFS | ZFS verifica y repara todos los datos del pool. No se inicia si el pool está degradado o ya hay un scrub/resilver en curso. | desactivada, 2º domingo 02:00 |
| Resumen del estado | Envía el estado completo por los canales de aviso. | desactivada, lunes 09:00 |

**Servidores sin ZFS**: Disk Monitor detecta solo si hay pools (en cada revisión). Si no hay, la sección de pools no aparece, el botón **+ Scrub ZFS** se oculta y una tarea de scrub existente (por ejemplo, importada de otro servidor) queda **inactiva** sin dar errores; si más adelante se crea un pool, empieza a funcionar sola.

Con **+ Prueba SMART**, **+ Scrub ZFS** y **+ Resumen** se agregan más tareas (por ejemplo, una prueba larga sólo para ciertos discos). Si un scrub y una prueba larga quedan a menos de 24 h, la pestaña lo advierte.

**Scrubs del sistema**: muchas distribuciones ya programan un scrub mensual (Ubuntu/Debian: `/etc/cron.d/zfsutils-linux`). Disk Monitor los detecta, los muestra en la pestaña Tareas con su horario en palabras y avisa cuando terminan. Si prefieres manejarlos desde Disk Monitor, activa la tarea **Scrub ZFS** y desactiva los del sistema con el comando que muestra la pestaña.

> La **prueba larga** y el **scrub** son pesados: prográmalos en horas de poco uso y separados entre sí y de los respaldos.

**Ignorar un disco**: en su detalle, botón **Ignorar alertas de este disco**. Sigue apareciendo en el panel, pero no genera avisos.

---

## 7. Publicarlo con un dominio (proxy inverso)

La aplicación habla HTTP en el puerto configurado. Para usar HTTPS y un dominio, ponle delante un proxy inverso:

- **Nginx Proxy Manager / Traefik / Caddy**: crea un host apuntando a `http://IP-DEL-SERVIDOR:8093`.
- **Nginx** a mano:

  ```nginx
  location / {
      proxy_pass http://127.0.0.1:8093;
      proxy_set_header Host $host;
      proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
      proxy_set_header X-Forwarded-Proto $scheme;
  }
  ```

Con `X-Forwarded-Proto: https` desde un proxy confiable (ver `TRUSTED_PROXIES`) la cookie de sesión se marca como segura. Después pon la URL pública en Configuración → General para que los avisos incluyan el enlace.

Si sólo lo usarás detrás del proxy, puedes publicar el puerto únicamente en localhost cambiando en `docker-compose.yml` la línea de `ports` por `"127.0.0.1:${HOST_PORT:-8093}:8000"`.

---

## 8. Instalarlo en varios servidores

Clona el repositorio en cada servidor siguiendo la [sección 2](#2-instalación-rápida). Cada instalación es independiente y detecta sus propios discos al iniciar.

**Copiar la configuración** (canales, umbrales, horarios) de un servidor a otro:

1. En el servidor de origen: Configuración → General → **Exportar configuración**. Usa **Exportar sin contraseñas** si el archivo va a circular.
2. En el nuevo: Configuración → General → **Importar…**

No se copian el nombre del servidor, la URL ni los discos ignorados, porque son propios de cada equipo. Si importas una exportación sin contraseñas, se conservan las que ya tenga el destino (también las URLs de Apprise), salvo que el archivo cambie el servidor de correo o los chats de Telegram: en ese caso hay que volver a escribir la contraseña o el token. El archivo se valida antes de aplicarse.

Pon un **nombre de servidor** distinto en cada uno (Configuración → General) para distinguir de dónde viene cada aviso; por defecto se usa el hostname.

---

## 9. Mantenimiento

| Tarea | Comando (dentro de la carpeta `disk-monitor`) |
|---|---|
| Ver logs | `docker compose logs -f` |
| Reiniciar | `docker compose restart` |
| Aplicar cambios del `.env` | `docker compose up -d` (con `restart` **no** se recargan las variables) |
| Actualizar a una versión nueva | `git pull && ./install.sh` (se conservan `data/` y `.env`, que git no toca). Si instalaste con el ZIP: descarga el nuevo, descomprímelo y copia su contenido sobre la carpeta (`unzip -o main.zip && cp -r Disk-Monitor-main/. disk-monitor/`), luego `cd disk-monitor && sh install.sh`. Los horarios de versiones anteriores se convierten solos en tareas. |
| Detener | `docker compose down` |
| Respaldar | copia `data/disk-monitor.db` y `.env` |
| Cambiar la contraseña | edita `APP_PASSWORD` en `.env` y luego `docker compose up -d` (cierra las sesiones abiertas) |
| Desinstalar | `docker compose down --rmi local` y borra la carpeta |

El historial se depura solo según los "días de historial" configurados (120 por defecto).

---

## 10. Solución de problemas

**No aparece ningún disco / "no se puede leer SMART"**
- El contenedor debe correr con `privileged: true` y con `/dev` montado (ya viene así en el `docker-compose.yml`).
- En una VM, los discos virtuales no tienen SMART: pasa el disco o la HBA completa (passthrough) a la VM, o instala Disk Monitor en el hipervisor.
- Comprueba desde dentro del contenedor:
  ```sh
  docker exec disk-monitor smartctl --scan-open
  docker exec disk-monitor smartctl -x /dev/sda
  ```

**Discos detrás de una controladora RAID no aparecen**
`smartctl --scan-open` detecta MegaRAID/cciss/Areca de forma automática. Si tu controladora no aparece, puede que el firmware no exponga SMART a través del arreglo; revisa la documentación de smartctl para tu modelo (`-d megaraid,N`, `-d cciss,N`, etc.).

**Un disco aparece "En reposo"**
Está detenido (spin-down) y, con la opción "No despertar discos en reposo", se muestra su última lectura. Si nunca se había leído (por ejemplo, recién instalado), se despierta una sola vez para tener datos. Desactívala si prefieres leerlo siempre (lo despertará en cada revisión).

**ZFS no aparece**
Sólo se muestra si el host tiene el módulo ZFS cargado (`/dev/zfs`). El panel indica si se usa el `zpool` del host o el del contenedor. Para comprobarlo: `docker exec disk-monitor zpool status`.

**No llegan los avisos**
- Usa **Enviar prueba** en cada canal; el resultado y el error aparecen en pantalla.
- En la pestaña **Actividad** está el detalle de cada envío.
- Revisa que el servidor tenga salida a internet y DNS desde Docker: `docker exec disk-monitor getent hosts api.telegram.org`

**Las horas de las tareas están desfasadas**
Ajusta `TZ` en el `.env` y aplica con `docker compose up -d`.

**El puerto está ocupado**
Cambia `HOST_PORT` en el `.env` y ejecuta `docker compose up -d`.

---

## 11. Seguridad

- El contenedor es **privilegiado** (tiene acceso total al hardware del host). Trata la web como un panel de administración: contraseña fuerte y sin exponerla directamente a internet. Usa un proxy inverso con HTTPS, una VPN o publica el puerto sólo en la red interna.
- El login bloquea por 15 minutos una IP tras 10 intentos fallidos.
- Las contraseñas de Telegram y SMTP se guardan en `data/disk-monitor.db` y la web nunca las muestra (aparecen enmascaradas). La aplicación deja `data/` y la base sólo legibles por su dueño (700/600) y `install.sh` crea el `.env` con permisos 600; no los abras a otros usuarios.
- La exportación de configuración **incluye** los secretos, salvo que uses "Exportar sin contraseñas" (que quita contraseña SMTP, token de Telegram y URLs de Apprise).

---

## 12. Referencia

**Qué detecta**

| Origen | Gravedad | Condición |
|---|---|---|
| SMART | 🔴 | El disco reporta FAILED, o un atributo de pre-falla está bajo el umbral |
| SMART | 🔴 | Sectores pendientes o incorregibles; la última prueba SMART falló |
| SMART | 🟡 / 🔴 | Sectores reasignados (umbrales de aviso y crítico) |
| SMART | 🟡 / 🔴 | Temperatura (umbrales distintos para HDD y SSD/NVMe) |
| SSD/NVMe | 🟡 / 🔴 | Desgaste, reserva disponible, `critical_warning`, errores de medio |
| SAS | 🟡 / 🔴 | Lista de defectos crecida, errores de E/S sin corregir |
| Eventos | 🟡 | Sube algún contador: reasignados, pendientes, CRC, log de errores, bloques malos… |
| Inventario | 🔴 / 🔵 | Desaparece un disco conocido / aparece un disco nuevo |
| ZFS | 🔴 | Pool no ONLINE (incluye DEGRADED) o errores de datos |
| ZFS | 🟡 | Errores de lectura/escritura/checksum en vdevs, errores en el último scrub, scrub antiguo |
| Espacio | 🟡 / 🔴 | Sistema de archivos o pool sobre el umbral de uso |

**Por qué el contenedor necesita privilegios**

| Opción | Motivo |
|---|---|
| `privileged: true` | `smartctl` envía comandos directos a los discos y a las controladoras. |
| `/dev:/dev` | Acceso a `/dev/sdX`, `/dev/nvmeX`, `/dev/zfs` y `/dev/disk/by-id`. |
| `pid: host` | Leer los montajes y el espacio libre del host (`/proc/1`) y usar su `zpool` (`nsenter`). |
| `/run/udev` (sólo lectura) | Datos de udev para identificar modelos y números de serie. Si no existe en el host no pasa nada. |

**API** (para scripts y monitoreo externo; acepta Basic Auth con las credenciales del `.env`):

| Método | Ruta | Uso |
|---|---|---|
| GET | `/health` | Sin autenticación. Devuelve `{"ok": true, "version": "1.2.3", "last_check": <epoch>, "language": "es"}` |
| GET | `/api/status` | Estado completo: discos, pools, sistemas de archivos y alertas activas |
| GET | `/api/inventory` | Inventario de discos (presentes y ausentes) |
| POST | `/api/check` | Lanzar una revisión |
| POST | `/api/discover` | Detectar discos y revisar |
| POST | `/api/selftest` | `{"type": "short"\|"long", "disks": [claves]}` |
| GET | `/api/tasks` | Tareas programadas con próxima y última ejecución |
| POST | `/api/tasks/{id}/run` | Ejecutar una tarea ahora (`check`, `smart-short`, `scrub`, `report`…) |
| POST | `/api/zfs/{pool}/scrub` | `{"action": "start"\|"pause"\|"stop"}` |
| GET | `/api/alerts` | Historial de alertas |

Ejemplo: `curl -u admin:CONTRASEÑA -X POST http://localhost:8093/api/check`

**Archivos**

| Ruta | Contenido |
|---|---|
| `.env` | Credenciales, puerto, zona horaria e idioma inicial |
| `data/disk-monitor.db` | Base SQLite: configuración, inventario, historial, alertas y avisos |
| `install.sh` | Instalación o actualización |
| `VERSION` | Versión instalada (se muestra al pie de la web) |

---

## Licencia

Disk Monitor es software libre bajo la [Licencia Apache 2.0](LICENSE). Puedes usarlo, modificarlo, hacer forks y redistribuirlo, también con fines comerciales, siempre que:

- conserves los archivos `LICENSE` y `NOTICE` en tu copia o versión derivada, con el crédito al proyecto original: **Disk Monitor de [KqK.cl](https://kqk.cl)** — <https://github.com/r34lcl/Disk-Monitor>;
- indiques en los archivos que modifiques que fueron cambiados.

Se entrega «tal cual», sin garantías. Ver el texto completo en `LICENSE`.
