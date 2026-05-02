import network
import utime
from lib.display import info, ok, warn, err, line
import config

_MGMT = {
    0: "AssocReq",  1: "AssocResp", 2: "ReassocReq", 3: "ReassocResp",
    4: "ProbeReq",  5: "ProbeResp", 8: "Beacon",
    10: "Disassoc", 11: "Auth",     12: "Deauth",
}
_TYPES = {0: "MGMT", 1: "CTRL", 2: "DATA", 3: "EXT"}

_stats = {"total": 0, "mgmt": 0, "ctrl": 0, "data": 0}


def _mac(buf, off):
    return "{:02x}:{:02x}:{:02x}:{:02x}:{:02x}:{:02x}".format(
        buf[off], buf[off+1], buf[off+2], buf[off+3], buf[off+4], buf[off+5]
    )


def parse(buf):
    """Décode l'en-tête MAC 802.11. Retourne un dict ou None si trame trop courte."""
    if len(buf) < 24:
        return None
    fc0     = buf[0]
    ftype   = (fc0 >> 2) & 0x03
    subtype = (fc0 >> 4) & 0x0F
    return {
        "type":      ftype,
        "tname":     _TYPES.get(ftype, "?"),
        "subtype":   subtype,
        "sname":     _MGMT.get(subtype, str(subtype)) if ftype == 0 else str(subtype),
        "protected": bool(buf[1] & 0x40),
        "addr1":     _mac(buf, 4),
        "addr2":     _mac(buf, 10),
        "addr3":     _mac(buf, 16),
        "len":       len(buf),
    }


def _check_esp():
    import esp
    if not hasattr(esp, "wifi_set_promiscuous"):
        err("Firmware standard — promiscuous indisponible")
        err("Compiler le firmware custom : bash tools/build_firmware.sh")
        return None
    return esp


def sniff(duration=30, channel=None):
    """
    Capture les trames 802.11 pendant `duration` secondes.
    channel=None  → channel hopping automatique.
    channel=N     → capture fixée sur le canal N.
    """
    global _stats
    esp = _check_esp()
    if esp is None:
        return None

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    _stats = {"total": 0, "mgmt": 0, "ctrl": 0, "data": 0}
    esp.wifi_set_promiscuous(True)

    if channel is not None:
        wlan.config(channel=channel)
        info("Canal fixé sur {}".format(channel))
    else:
        info("Channel hopping — canaux {} à {}".format(
            config.CHANNELS[0], config.CHANNELS[-1]
        ))

    t_start  = utime.ticks_ms()
    ch_idx   = 0
    last_log = 0

    try:
        while utime.ticks_diff(utime.ticks_ms(), t_start) < duration * 1000:
            # Vider le ring buffer C
            pkt = esp.wifi_get_pkt()
            while pkt is not None:
                f = parse(pkt)
                if f:
                    _stats["total"] += 1
                    t = f["type"]
                    if   t == 0: _stats["mgmt"] += 1
                    elif t == 1: _stats["ctrl"] += 1
                    elif t == 2: _stats["data"] += 1
                    if config.DEBUG and t == 0:
                        info("[{}][{}] {} → {}".format(
                            f["tname"], f["sname"], f["addr2"], f["addr1"]
                        ))
                pkt = esp.wifi_get_pkt()

            # Channel hop
            if channel is None:
                ch = config.CHANNELS[ch_idx % len(config.CHANNELS)]
                wlan.config(channel=ch)
                ch_idx += 1

            elapsed = utime.ticks_diff(utime.ticks_ms(), t_start) // 1000
            if elapsed - last_log >= 5 and elapsed > 0:
                last_log = elapsed
                info("{}s — total={} mgmt={} ctrl={} data={}".format(
                    elapsed, _stats["total"],
                    _stats["mgmt"], _stats["ctrl"], _stats["data"]
                ))

            utime.sleep_ms(config.HOP_INTERVAL)

    except KeyboardInterrupt:
        warn("Capture interrompue")
    finally:
        esp.wifi_set_promiscuous(False)

    line()
    ok("Fin — {} trames  (mgmt={} ctrl={} data={})".format(
        _stats["total"], _stats["mgmt"], _stats["ctrl"], _stats["data"]
    ))
    return dict(_stats)
