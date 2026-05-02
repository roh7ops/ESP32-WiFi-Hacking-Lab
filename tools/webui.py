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

PORT_SERIAL = "/dev/ttyUSB0"
WEB_PORT    = 8080
BASE_DIR    = Path(__file__).parent.parent
VENV_PY     = BASE_DIR / ".venv/bin/python3"
MPREMOTE    = BASE_DIR / ".venv/bin/mpremote"

app = Flask(__name__)

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
    data   = request.json or {}
    mode   = data.get("mode", "random")
    ssid   = data.get("ssid", "")
    ch     = int(data.get("channel", 6))
    count  = int(data.get("count", 50))
    if mode == "random":
        code = f"from lib.beacon_spam import spam_random\nspam_random(channel={ch}, count={count})\nprint('OK')\n"
    elif mode == "fr":
        code = f"from lib.beacon_spam import spam_fr\nspam_fr(channel={ch})\nprint('OK')\n"
    elif mode == "clone" and ssid:
        code = f"from lib.beacon_spam import spam_clone\nspam_clone('{ssid}', channel={ch}, count={count})\nprint('OK')\n"
    else:
        return jsonify({"ok": False, "error": "Mode invalide"}), 400
    r = mp_exec(code, timeout=30)
    return jsonify({"ok": r["ok"], "out": r["out"], "error": r["err"]})


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
