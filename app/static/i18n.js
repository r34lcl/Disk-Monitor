// Traducción de la interfaz. El texto en español es la clave; si falta una traducción se muestra en español.
let LANG = "es", LOC = "es-CL";
try { const l = localStorage.getItem("dm_lang"); if (l === "en") { LANG = "en"; LOC = "en-US"; } } catch (e) {}
function setLang(l) {
  LANG = l === "en" ? "en" : "es"; LOC = LANG === "en" ? "en-US" : "es-CL";
  document.documentElement.lang = LANG;
  try { localStorage.setItem("dm_lang", LANG); } catch (e) {}
}
function _t(s, v) {
  let o = (LANG === "en" && I18N_EN[s]) || s;
  if (v) o = o.replace(/\{(\w+)\}/g, (m, k) => (k in v ? v[k] : m));
  return o;
}
function tStatic() {
  document.querySelectorAll("[data-tt]").forEach(e => e.title = _t(e.title));
  document.querySelectorAll("[data-t]").forEach(e => e.textContent = _t(e.textContent));
  document.querySelectorAll("[aria-label]").forEach(e => e.setAttribute("aria-label", _t(e.getAttribute("aria-label"))));
}
const I18N_EN = {
  // navegación y general
  "Panel": "Dashboard", "Alertas": "Alerts", "Tareas": "Tasks", "Actividad": "Activity", "Configuración": "Settings",
  "Salir": "Log out", "Cerrar sesión": "Log out", "Cerrar": "Close", "Cerrar detalle": "Close details",
  "Usuario": "Username", "Contraseña": "Password", "Recordarme 30 días": "Remember me for 30 days", "Entrar": "Sign in",
  "nunca": "never", " día": " day", " días": " days", " años": " years", "hace {v}": "{v} ago", "en {v}": "in {v}",
  "Listo": "Done", "Guardar": "Save", "Guardado": "Saved", "Cancelar": "Cancel", "Editar": "Edit", "sí": "yes", "no": "no",
  "todos": "all", "ahora": "now",
  // estados
  "Sin SMART": "No SMART", "Sano": "Healthy", "Aviso": "Warning", "Crítico": "Critical", "Info": "Info", "Ignorado": "Ignored",
  "Sin datos": "No data", "En reposo": "Standby", "Presente": "Present", "Ausente": "Missing",
  "{n} críticos": "{n} critical", "{n} crítico": "{n} critical", "{n} avisos": "{n} warnings", "{n} aviso": "{n} warning",
  "Todo en orden": "All good", "aviso": "warning", "crítico": "critical",
  // panel
  "zpool del host": "host zpool", "zpool del contenedor": "container zpool", "no disponible": "not available",
  "Última revisión": "Last check", "próxima": "next", "Detectar discos": "Detect disks", "Detectando…": "Detecting…",
  "Vuelve a buscar discos conectados y muestra el inventario": "Looks for connected disks again and shows the inventory",
  "Revisando…": "Checking…", "Revisar ahora": "Check now", "Datos desactualizados:": "Stale data:",
  'la revisión programada no se ejecutó (debía correr {a}; la última fue {b}). Revisa los logs del contenedor o pulsa "Revisar ahora".':
    'the scheduled check did not run (it was due {a}; the last one was {b}). Check the container logs or press "Check now".',
  "Problemas activos": "Active problems", "Discos ausentes": "Missing disks", "Último visto como {dev} {ago}": "Last seen as {dev} {ago}",
  "Olvidar disco": "Forget disk", "Olvidar": "Forget", "Discos físicos": "Physical disks", "No se detectaron discos": "No disks detected",
  "Pools ZFS": "ZFS pools", "Sistemas de archivos": "File systems",
  "Montaje": "Mount", "Origen": "Source", "Tipo": "Type", "Uso": "Usage", "Usado": "Used", "Libre": "Free", "Total": "Total",
  "desde": "since", "visto": "seen", "silenciado": "muted",
  "Volver a recibir recordatorios": "Receive reminders again", "No enviar más recordatorios de este problema": "Stop sending reminders for this problem",
  "Reactivar": "Unmute", "Silenciar": "Mute",
  "Temperatura últimas 24 h": "Temperature, last 24 h", "Aún no hay suficiente historial": "Not enough history yet",
  "Encendido": "Powered on", "Desgaste": "Wear", "Reserva": "Spare", "Errores medio": "Media errors", "Defectos": "Defects",
  "E/S sin corregir": "Uncorrected I/O", "Reasignados": "Reallocated", "Pendientes": "Pending", "Incorregibles": "Uncorrectable",
  "Bloques malos": "Bad blocks", "Errores CRC": "CRC errors", "Escrito": "Written",
  "Prueba en curso": "Test running", " · falta {n}%": " · {n}% left", "Última prueba:": "Last test:",
  "Sin pruebas SMART registradas": "No SMART tests recorded", "Ver detalle de": "View details of",
  "Este dispositivo no entrega datos SMART (disco virtual, adaptador USB o controladora que no los expone). Sólo se vigila que siga presente.":
    "This device does not report SMART data (virtual disk, USB adapter or a controller that hides it). Only its presence is monitored.",
  "datos de {ago}": "data from {ago}",
  // pools
  "en pausa": "paused", "en curso": "in progress", " · faltan {d}": " · {d} left", "Avance del {w}": "{w} progress",
  "Reanudar": "Resume", "Pausar": "Pause", "Detener": "Stop", "Último scrub": "Last scrub", "{n} errores": "{n} errors",
  "sin errores": "no errors", " · duró {d}": " · took {d}", "El último scrub se canceló": "The last scrub was canceled",
  "Sin scrub registrado": "No scrub recorded", "próximo": "next", "El pool no está sano": "The pool is not healthy",
  "Iniciar scrub": "Start scrub", "{a} de {b}": "{a} of {b}", "{pct}% usado · quedan {free}": "{pct}% used · {free} free",
  "Estado": "State", "Lect": "Read", "Escr": "Write",
  "¿Detener el scrub de {pool}? Si lo inicias de nuevo, parte desde el principio.":
    "Stop the scrub of {pool}? If you start it again, it starts over from the beginning.",
  "¿Iniciar un scrub de {pool} ahora? Lee todos los datos del pool y puede tardar varias horas; el servidor seguirá funcionando, pero los discos estarán más ocupados.":
    "Start a scrub of {pool} now? It reads all the data in the pool and can take several hours; the server keeps working, but the disks will be busier.",
  "Revisión lista: {d} discos, {i} problemas": "Check done: {d} disks, {i} problems", " (aviso enviado)": " (notification sent)",
  // inventario
  "Inventario de discos": "Disk inventory",
  "Primer inventario de este servidor: {n} discos registrados. Desde ahora se avisará si alguno desaparece o aparece uno nuevo.":
    "First inventory of this server: {n} disks recorded. From now on you will be notified if one disappears or a new one shows up.",
  "{n} discos detectados": "{n} disks detected", "{n} nuevo(s)": "{n} new", "sin discos nuevos": "no new disks", "{n} ausente(s)": "{n} missing",
  "Disco": "Disk", "Modelo": "Model", "Serie": "Serial", "Visto": "Seen",
  "La detección se hace al iniciar el contenedor, en cada revisión, con este botón y con un sondeo rápido cada {n} min que no despierta los discos (pestaña Tareas).":
    "Detection runs when the container starts, on every check, with this button and with a quick probe every {n} min that does not wake the disks (Tasks tab).",
  "¿Dejar de vigilar este disco ausente?": "Stop monitoring this missing disk?",
  "Disco olvidado; la alerta se cierra en la próxima revisión": "Disk forgotten; the alert closes on the next check",
  // detalle de disco
  "Dispositivo": "Device", "Familia": "Family", "Capacidad": "Capacity", "Enlace": "Link", "Formato": "Form factor",
  "Horas encendido": "Power-on hours", "Ciclos de encendido": "Power cycles", "Temp. actual / máx. histórica": "Current temp. / lifetime max.",
  "Pool / montaje": "Pool / mount", "Leído / escrito": "Read / written", "Clave interna": "Internal key",
  "FALLA": "FAILED", "Correcto (PASSED)": "OK (PASSED)", "Prueba corta": "Short test", "Prueba larga": "Long test",
  "Volver a vigilar": "Monitor again", "Ignorar alertas de este disco": "Ignore alerts for this disk",
  "Temperatura": "Temperature", "Atributos SMART": "SMART attributes", "Atributo": "Attribute", "Valor": "Value", "Peor": "Worst",
  "Umbral": "Threshold", "Falló": "Failed", "pre-falla": "pre-fail", "uso": "usage", "Sin atributos": "No attributes",
  "Pruebas SMART": "SMART tests", "Resultado": "Result", "Hora de vida": "Lifetime hour", "LBA error": "Error LBA",
  "El disco no tiene pruebas registradas": "The disk has no recorded tests", "Log de errores ATA": "ATA error log",
  "Hora": "Hour", "Descripción": "Description", "Alertas de este disco": "Alerts for this disk", "Gravedad": "Severity",
  "Alerta": "Alert", "Inicio": "Start", "Resuelta": "Resolved", "evento": "event", "activa": "active",
  "Sin alertas registradas": "No alerts recorded", "Temperatura de {name}": "Temperature of {name}",
  "La prueba larga puede durar muchas horas en discos grandes y reduce el rendimiento mientras corre. ¿Iniciar?":
    "The long test can take many hours on large disks and reduces performance while it runs. Start it?",
  "Prueba iniciada": "Test started", "No se pudo iniciar: ": "Could not start: ", "Disco no disponible": "Disk not available",
  "Disco ignorado (aplica en la próxima revisión)": "Disk ignored (applies on the next check)", "El disco vuelve a vigilarse": "The disk is monitored again",
  // alertas y actividad
  "Activas": "Active", "No hay problemas activos": "No active problems", "Historial": "History", "Fin": "End", "Avisada": "Notified",
  "problema": "problem", "Sin historial": "No history", "Avisos enviados": "Notifications sent", "Fecha": "Date",
  "Aún no se ha enviado ningún aviso": "No notifications sent yet", "Revisiones": "Checks", "Duración": "Duration",
  "Discos": "Disks", "Críticos": "Critical", "Avisos": "Warnings", "Eventos": "Events", "Notificó": "Notified",
  "manual": "manual", "programada": "scheduled", "inicio": "startup", "resumen": "summary", "detección manual": "manual detection",
  "cambio de hardware": "hardware change", "cambio de idioma": "language change", "seguimiento de prueba SMART": "SMART test follow-up",
  // configuración
  "Los horarios de revisión, pruebas SMART, scrub y resumen ahora están en la pestaña":
    "Schedules for checks, SMART tests, scrubs and the summary are now under",
  "Umbrales": "Thresholds", "Enviar prueba": "Send test", "Correo (SMTP)": "Email (SMTP)", "Otros servicios (Apprise)": "Other services (Apprise)",
  "Una URL por línea": "One URL per line",
  "Discord, Slack, ntfy, Pushover, Gotify, WhatsApp, Signal, Matrix, Teams y más de 100 servicios. Formatos en github.com/caronc/apprise/wiki":
    "Discord, Slack, ntfy, Pushover, Gotify, WhatsApp, Signal, Matrix, Teams and 100+ more services. Formats at github.com/caronc/apprise/wiki",
  "General": "General", "Vacío =": "Empty =", "Para el enlace en los avisos, p.ej. {url}": "For the link in notifications, e.g. {url}",
  "Exportar configuración": "Export settings", "Exportar sin contraseñas": "Export without passwords", "Importar…": "Import…",
  "Para replicar canales, umbrales y horarios en otro servidor (no copia nombre, URL ni discos ignorados).":
    "To copy channels, thresholds and schedules to another server (name, URL and ignored disks are not copied).",
  "Discos ignorados: {list} (se cambia desde el detalle del disco)": "Ignored disks: {list} (change it from the disk details)",
  "Configuración guardada": "Settings saved", "Configuración importada": "Settings imported", "No se pudo importar: ": "Could not import: ",
  "Enviando…": "Sending…", "No hay canales activados": "No channels enabled",
  "Avisar desde": "Notify from", "Recordatorio cada (horas)": "Reminder every (hours)",
  "Repite el aviso de problemas sin resolver. 0 = nunca": "Repeats the notification for unresolved problems. 0 = never",
  "Avisar cuando un problema se resuelve": "Notify when a problem is resolved",
  "Pruebas SMART lanzadas fuera de las tareas: avisar también si terminan bien": "SMART tests started outside the tasks: notify even when they pass",
  "Scrubs lanzados fuera de Disk Monitor (p.ej. cron del sistema): avisar al iniciar y al terminar":
    "Scrubs started outside Disk Monitor (e.g. system cron): notify when they start and finish",
  "Avisar cuando se detecta un disco nuevo": "Notify when a new disk is detected",
  "Avisos y críticos": "Warnings and critical", "Sólo críticos": "Critical only",
  "Activado": "Enabled", "Crea el bot con @BotFather": "Create the bot with @BotFather",
  "Chat IDs (separados por coma)": "Chat IDs (comma separated)",
  "Usuario, grupo o canal. Para grupos el ID empieza con -100": "User, group or channel. Group IDs start with -100",
  "Avisos sin sonido (los críticos siempre suenan)": "Silent warnings (critical ones always make a sound)",
  "Servidor": "Server", "Puerto": "Port", "Seguridad": "Security", "Ninguna": "None", "Remitente": "Sender",
  "Vacío = el usuario": "Empty = the username", "Destinatarios (separados por coma)": "Recipients (comma separated)",
  "Idioma / Language": "Language / Idioma", "Nombre del servidor en los avisos": "Server name in notifications",
  "URL pública de este panel": "Public URL of this dashboard", "Guardar historial (días)": "Keep history (days)",
  "Montajes a ignorar (coma)": "Mounts to ignore (comma)",
  "Temp. HDD aviso (°C)": "HDD temp. warning (°C)", "Temp. HDD crítica (°C)": "HDD temp. critical (°C)",
  "Temp. SSD/NVMe aviso (°C)": "SSD/NVMe temp. warning (°C)", "Temp. SSD/NVMe crítica (°C)": "SSD/NVMe temp. critical (°C)",
  "Sectores reasignados: aviso desde": "Reallocated sectors: warning from", "Sectores reasignados: crítico desde": "Reallocated sectors: critical from",
  "Sectores pendientes: crítico desde": "Pending sectors: critical from", "Incorregibles offline: crítico desde": "Offline uncorrectable: critical from",
  "Errores reportados: aviso desde": "Reported errors: warning from", "Desgaste SSD aviso (%)": "SSD wear warning (%)",
  "Desgaste SSD crítico (%)": "SSD wear critical (%)", "Reserva NVMe aviso bajo (%)": "NVMe spare warning below (%)",
  "Uso de disco/pool aviso (%)": "Disk/pool usage warning (%)", "Uso de disco/pool crítico (%)": "Disk/pool usage critical (%)",
  "Máx. días sin scrub ZFS": "Max. days without ZFS scrub", "0 = no vigilar": "0 = don't monitor",
  // tareas
  "Tareas programadas": "Scheduled tasks",
  "Activa, desactiva o cambia el horario de cada una. Las horas son las del servidor ({tz}, ahora {now}).":
    "Enable, disable or change the schedule of each one. Times are in the server's time zone ({tz}, now {now}).",
  "Prueba SMART": "SMART test", "Scrub ZFS": "ZFS scrub", "Resumen": "Summary",
  "Prueba SMART larga": "Long SMART test", "Prueba SMART corta": "Short SMART test", "Revisión de discos": "Disk check", "Resumen del estado": "Status summary",
  "El servidor ya programa scrubs por su cuenta": "The server already schedules scrubs on its own", " y también activaste uno aquí": " and you also enabled one here",
  "Para no correr scrubs duplicados (cada uno tarda horas), desactiva los del sistema ejecutando en el servidor:":
    "To avoid duplicate scrubs (each one takes hours), disable the system ones by running this on the server:",
  "Disk Monitor igual detecta esos scrubs y avisa cuando terminan. Si prefieres manejarlos desde aquí, activa la tarea «Scrub ZFS» y desactiva los del sistema:":
    "Disk Monitor still detects those scrubs and notifies when they finish. If you prefer to manage them here, enable the “ZFS scrub” task and disable the system ones:",
  "Detección de discos": "Disk detection",
  "Revisa cada pocos minutos si se conectó o retiró un disco (no despierta discos en reposo). Si cambia algo, lanza una revisión completa.":
    "Checks every few minutes whether a disk was connected or removed (does not wake sleeping disks). If something changed, it runs a full check.",
  "Cada (minutos)": "Every (minutes)", "0 = desactivada": "0 = disabled",
  "No despertar discos en reposo al revisar (usa la última lectura)": "Don't wake sleeping disks during checks (uses the last reading)",
  "Lee el estado SMART de los discos, los pools ZFS y el espacio libre. Si encuentra un problema, avisa.":
    "Reads the SMART status of the disks, the ZFS pools and free space. If it finds a problem, it notifies you.",
  "El disco se autodiagnostica en 1–2 minutos, sin afectar el uso normal.": "The disk runs a self-test in 1–2 minutes without affecting normal use.",
  "El disco lee toda su superficie. Sigue usable mientras tanto, pero más lento: en discos grandes tarda horas (12 TB ≈ 18–23 h).":
    "The disk reads its whole surface. It stays usable meanwhile, but slower: on large disks it takes hours (12 TB ≈ 18–23 h).",
  "ZFS lee y verifica todos los datos del pool y repara lo que encuentre dañado. Los discos quedan ocupados mientras dura.":
    "ZFS reads and verifies all the data in the pool and repairs anything damaged. The disks stay busy while it runs.",
  "Envía por los canales de aviso un resumen con el estado de todos los discos, aunque no haya problemas.":
    "Sends a summary of every disk's status through the notification channels, even when there are no problems.",
  "Desactivar": "Disable", "Activar": "Enable", "Tarea": "Task", "Horario": "Schedule", "Próxima": "Next",
  "inactiva: ": "inactive: ", "desactivada": "disabled", "En ejecución…": "Running…", "Última": "Last", " (manual)": " (manual)",
  "Coincide en menos de 24 h con otra tarea pesada (scrub / prueba larga). Conviene separarlas.":
    "It falls within 24 h of another heavy task (scrub / long test). Better to space them out.",
  "Ejecutar ahora": "Run now", "Repetir": "Repeat", "Cada cierto tiempo": "At an interval", "Todos los días": "Every day",
  "Ciertos días de la semana": "Certain weekdays", "Una vez al mes (día fijo)": "Once a month (fixed day)",
  "Una vez al mes (p.ej. 2º domingo)": "Once a month (e.g. 2nd Sunday)", "Avanzado (cron)": "Advanced (cron)",
  "Cada": "Every", "Unidad": "Unit", "minutos": "minutes", "horas": "hours", "Día del mes": "Day of month",
  "Del 29 al 31 se salta los meses más cortos": "Days 29 to 31 skip shorter months", "Semana": "Week", "Día": "Day",
  "Primer": "First", "Segundo": "Second", "Tercer": "Third", "Cuarto": "Fourth",
  "Expresión cron (minuto hora día mes día-semana)": "Cron expression (minute hour day month weekday)",
  "Ojo: si fijas día del mes y día de la semana, cron corre en <b>ambos</b> casos.": "Note: if you set both day of month and weekday, cron runs in <b>both</b> cases.",
  "Días": "Days", "Días de la semana": "Weekdays", "Tipo de prueba": "Test type", "Corta (1–2 min)": "Short (1–2 min)", "Larga (horas)": "Long (hours)",
  "Discos (ninguno marcado = todos)": "Disks (none selected = all)", "Pools (ninguno marcado = todos)": "Pools (none selected = all)",
  "Si el pool está degradado o ya tiene un scrub o resilver en curso, no se inicia.": "If the pool is degraded or already has a scrub or resilver running, it is not started.",
  "Avisar cuando empieza (con la hora estimada de término)": "Notify when it starts (with the estimated finish time)",
  'Avisar también cuando termina sin problemas <span class="muted">(si encuentra errores, avisa siempre)</span>':
    'Also notify when it finishes without problems <span class="muted">(errors are always notified)</span>',
  "Eliminar tarea": "Delete task", "próximas:": "next:", "Horario inválido": "Invalid schedule",
  "Tarea guardada": "Task saved", "Tarea activada": "Task enabled", "Tarea desactivada": "Task disabled",
  "¿Eliminar la tarea «{name}»?": "Delete the task “{name}”?", "Tarea eliminada": "Task deleted",
  "¿Iniciar el scrub ahora? Puede tardar varias horas y los discos estarán más ocupados.": "Start the scrub now? It can take several hours and the disks will be busier.",
  "¿Iniciar la prueba larga ahora? En discos grandes tarda muchas horas.": "Start the long test now? On large disks it takes many hours.",
  "Tarea iniciada": "Task started",
  "Lun": "Mon", "Mar": "Tue", "Mié": "Wed", "Jue": "Thu", "Vie": "Fri", "Sáb": "Sat", "Dom": "Sun",
  "domingo": "Sunday", "lunes": "Monday", "martes": "Tuesday", "miércoles": "Wednesday", "jueves": "Thursday", "viernes": "Friday", "sábado": "Saturday",
};
