import network
import utime
from lib.display import info, ok, warn, err, line, table
import config

_probes = {}


def _mac(buf, off):
    return "{:02x}:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}".format(
        buf[off], buf[off+1], buf[off+2], buf[off+3], buf[off+4], buf[off+5]
    )


def _extract_ssid(buf):
    """Lit l'IE SSID (type=0) depuis le corps d'une Probe Request (offset 24)."""
    if len(buf) < 26:
        return "<vide>"
    if buf[24] != 0 or buf[25] == 0:
        return "<broadcast>"
    end = 26 + buf[25]
    if end > len(buf):
        return "<tronqué>"
    try:
        return buf[26:end].decode("utf-8")
    except Exception:
        return "<binaire>"


def _process(buf):
    if len(buf) < 24:
        return
    fc0     = buf[0]
    ftype   = (fc0 >> 2) & 0x03
    subtype = (fc0 >> 4) & 0x0F
    if ftype != 0 or subtype != 4:
        return
    mac  = _mac(buf, 10)
    ssid = _extract_ssid(buf)
    key  = (mac, ssid)
    if key not in _probes:
        _probes[key] = 0
        info("Probe : {} cherche \"{}\"".format(mac, ssid))
    _probes[key] += 1


def _check_esp():
    import esp
    if not hasattr(esp, "wifi_set_promiscuous"):
        err("Firmware standard — promiscuous indisponible")
        err("Compiler le firmware custom : bash tools/build_firmware.sh")
        return None
    return esp


def sniff_probes(duration=60, channel=None):
    """Capture les Probe Requests pendant `duration` secondes."""
    global _probes
    esp = _check_esp()
    if esp is None:
        return None

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    _probes = {}
    esp.wifi_set_promiscuous(True)

    if channel is not None:
        wlan.config(channel=channel)
        info("Canal fixé sur {}".format(channel))
    else:
        info("Channel hopping actif")

    t_start = utime.ticks_ms()
    ch_idx  = 0

    try:
        while utime.ticks_diff(utime.ticks_ms(), t_start) < duration * 1000:
            pkt = esp.wifi_get_pkt()
            while pkt is not None:
                _process(pkt)
                pkt = esp.wifi_get_pkt()

            if channel is None:
                ch = config.CHANNELS[ch_idx % len(config.CHANNELS)]
                wlan.config(channel=ch)
                ch_idx += 1

            utime.sleep_ms(config.HOP_INTERVAL)

    except KeyboardInterrupt:
        warn("Capture interrompue")
    finally:
        esp.wifi_set_promiscuous(False)

    if not _probes:
        warn("Aucune probe request capturée")
        return {}

    line()
    ok("{} combinaison(s) MAC/SSID unique(s)".format(len(_probes)))
    table(
        ["MAC source", "SSID cherché", "Probes"],
        [[mac, ssid, count] for (mac, ssid), count in
         sorted(_probes.items(), key=lambda x: x[1], reverse=True)],
        col=22,
    )
    return dict(_probes)
