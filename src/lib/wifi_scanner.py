import network
import utime
from lib.display import info, ok, warn, table, line
import config

_AUTH = {
    0: "Open",
    1: "WEP",
    2: "WPA",
    3: "WPA2",
    4: "WPA/WPA2",
    5: "WPA3",
    6: "WPA2-Ent",
}


def _mac(raw):
    return ":".join("{:02x}".format(b) for b in raw)


def _ssid(raw):
    try:
        return raw.decode("utf-8") or "<masqué>"
    except Exception:
        return "<binaire>"


def scan(verbose=True):
    """Scan actif — retourne une liste de dicts triés par RSSI décroissant."""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    info("Scan en cours...")

    results = wlan.scan()

    nets = sorted(
        [
            {
                "ssid":   _ssid(r[0]),
                "bssid":  _mac(r[1]),
                "bssid_b": r[1],
                "ch":     r[2],
                "rssi":   r[3],
                "auth":   _AUTH.get(r[4], "?"),
                "auth_id": r[4],
                "hidden": bool(r[5]),
            }
            for r in results
        ],
        key=lambda x: x["rssi"],
        reverse=True,
    )

    if verbose:
        ok("{} réseau(x) détecté(s)".format(len(nets)))
        table(
            ["#", "SSID", "BSSID", "Ch", "RSSI", "Sécu"],
            [
                [i + 1, n["ssid"], n["bssid"], n["ch"],
                 "{} dBm".format(n["rssi"]), n["auth"]]
                for i, n in enumerate(nets)
            ],
            col=15,
        )

    return nets


def scan_loop(interval=10):
    """Scans répétés jusqu'à Ctrl+C."""
    i = 0
    try:
        while True:
            line()
            info("Scan #{}".format(i + 1))
            scan()
            i += 1
            utime.sleep(interval)
    except KeyboardInterrupt:
        warn("Scan stoppé")


def select(nets):
    """Affiche les réseaux et retourne le dict du réseau choisi, ou None."""
    if not nets:
        warn("Aucun réseau — lancez scan() d'abord")
        return None
    line()
    for i, n in enumerate(nets):
        print("  [{}] {} — {} — ch{} — {}".format(
            i + 1, n["ssid"], n["bssid"], n["ch"], n["auth"]
        ))
    line()
    try:
        idx = int(input("  Choisir un réseau (0 = annuler) : "))
        if 1 <= idx <= len(nets):
            return nets[idx - 1]
    except (ValueError, EOFError):
        pass
    return None
