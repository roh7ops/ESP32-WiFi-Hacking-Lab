import network
import socket
import struct
import utime
from lib.display import info, ok, warn, err, line
import config

# En-tête de chaque trame envoyée vers Kali :
# [timestamp 4B LE][length 2B LE][rssi 1B signé][canal 1B]
_HDR = struct.Struct('<IHbB')


def _connect():
    """Ouvre la connexion TCP vers le receiver Kali. Retourne le socket ou None."""
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        err("WiFi non connecté — se connecter au hotspot d'abord")
        return None
    try:
        s = socket.socket()
        s.connect((config.STREAM_HOST, config.STREAM_PORT))
        ok("Connecté à {}:{}".format(config.STREAM_HOST, config.STREAM_PORT))
        return s
    except OSError as e:
        err("Connexion échouée : {} — vérifier STREAM_HOST dans config.py".format(e))
        return None


def _check_esp():
    import esp
    if not hasattr(esp, 'wifi_set_promiscuous'):
        err("Firmware standard — promiscuous indisponible")
        err("Compiler le firmware custom : bash tools/build_firmware.sh")
        return None
    return esp


def start(duration=0, channel=None):
    """
    Capture les trames 802.11 en mode promiscuous et les envoie
    en temps réel vers Kali via TCP.

    duration=0  → infini jusqu'à Ctrl+C.
    channel=None → channel hopping automatique.
    """
    esp = _check_esp()
    if esp is None:
        return

    sock = _connect()
    if sock is None:
        return

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    esp.wifi_set_promiscuous(True)

    info("Streaming démarré → {}:{}".format(config.STREAM_HOST, config.STREAM_PORT))
    if channel is not None:
        wlan.config(channel=channel)
        info("Canal fixé : {}".format(channel))
    else:
        info("Channel hopping actif")

    t_start  = utime.ticks_ms()
    ch_idx   = 0
    sent     = 0
    errors   = 0
    last_log = 0

    try:
        while True:
            if duration > 0:
                elapsed = utime.ticks_diff(utime.ticks_ms(), t_start) // 1000
                if elapsed >= duration:
                    break

            # Vider le ring buffer C et envoyer chaque trame
            pkt = esp.wifi_get_pkt()
            while pkt is not None:
                length = len(pkt)
                ts     = utime.ticks_ms()
                canal  = config.CHANNELS[ch_idx % len(config.CHANNELS)] \
                         if channel is None else channel
                hdr = _HDR.pack(ts, length, 0, canal)  # rssi=0 (non dispo via ring buffer)
                try:
                    sock.sendall(hdr + pkt)
                    sent += 1
                except OSError:
                    errors += 1
                    if errors > 5:
                        warn("Trop d'erreurs réseau — streaming interrompu")
                        return
                pkt = esp.wifi_get_pkt()

            # Channel hop
            if channel is None:
                ch = config.CHANNELS[ch_idx % len(config.CHANNELS)]
                wlan.config(channel=ch)
                ch_idx += 1

            elapsed = utime.ticks_diff(utime.ticks_ms(), t_start) // 1000
            if elapsed - last_log >= 10:
                last_log = elapsed
                info("{}s — {} trames envoyées".format(elapsed, sent))

            utime.sleep_ms(config.HOP_INTERVAL)

    except KeyboardInterrupt:
        warn("Streaming stoppé")
    finally:
        esp.wifi_set_promiscuous(False)
        sock.close()

    line()
    ok("{} trames envoyées vers Kali".format(sent))
    return sent


def connect_ap(ssid, password=None, timeout=15):
    """
    Connecte l'ESP32 au hotspot Android (ou AP Kali) avant de streamer.
    À appeler une fois avant start().
    """
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected() and wlan.config('essid') == ssid:
        ok("Déjà connecté à \"{}\"".format(ssid))
        ok("IP : {}".format(wlan.ifconfig()[0]))
        return True

    info("Connexion à \"{}\"...".format(ssid))
    if password:
        wlan.connect(ssid, password)
    else:
        wlan.connect(ssid)

    t = utime.ticks_ms()
    while not wlan.isconnected():
        if utime.ticks_diff(utime.ticks_ms(), t) > timeout * 1000:
            err("Timeout — impossible de rejoindre \"{}\"".format(ssid))
            return False
        utime.sleep_ms(300)

    ok("Connecté à \"{}\"".format(ssid))
    ok("IP ESP32 : {}".format(wlan.ifconfig()[0]))
    return True
