#!/bin/bash
# Compile un firmware MicroPython ESP32 custom avec les fonctions WiFi hacking.
# Prérequis : Docker installé et démon démarré.

set -e

VERSION="v1.25.0"
BUILD_DIR="/run/media/roh/Sitoky140/Hacking/build-micropython"
OUT_DIR="$(cd "$(dirname "$0")/../firmware" && pwd)"
PORT="/dev/ttyUSB0"
PATCH_SCRIPT="$(cd "$(dirname "$0")" && pwd)/patch_modesp.py"

RED='\033[91m'; GREEN='\033[92m'; YELLOW='\033[93m'; RESET='\033[0m'

log()  { echo -e "${GREEN}[+]${RESET} $*"; }
warn() { echo -e "${YELLOW}[!]${RESET} $*"; }
die()  { echo -e "${RED}[x]${RESET} $*"; exit 1; }

# ── Vérifications ──────────────────────────────────────────────────────────────

command -v docker &>/dev/null || die "Docker non trouvé. Installer : sudo apt install docker.io"
command -v git    &>/dev/null || die "git non trouvé."
command -v python3 &>/dev/null || die "python3 non trouvé."

log "Démarrage du build firmware MicroPython $VERSION + WiFi hacking"

# ── Cloner MicroPython ─────────────────────────────────────────────────────────

if [ ! -d "$BUILD_DIR" ]; then
    log "Clonage MicroPython $VERSION..."
    git clone --depth 1 --branch "$VERSION" \
        https://github.com/micropython/micropython.git "$BUILD_DIR"
else
    warn "Sources déjà présentes dans $BUILD_DIR — on continue"
fi

# ── Appliquer le patch ─────────────────────────────────────────────────────────

log "Application du patch WiFi..."
python3 "$PATCH_SCRIPT" "$BUILD_DIR/ports/esp32/modesp.c"

# ── Build avec Docker (ESP-IDF v5.2 officiel) ──────────────────────────────────

log "Build Docker en cours (10-30 min à la première exécution)..."

mkdir -p /tmp/esp-home

docker run --rm \
    -v "$BUILD_DIR":/micropython \
    -v "/tmp/esp-home":/home/builder \
    -w /micropython \
    --user "$(id -u):$(id -g)" \
    -e HOME=/home/builder \
    espressif/idf:v5.2.2 \
    bash -c "
        set -e
        git config --global --add safe.directory /micropython
        pip install pyserial --quiet 2>/dev/null || true
        echo '[*] Initialisation des submodules...'
        make -C ports/esp32 BOARD=ESP32_GENERIC submodules
        echo '[*] Build mpy-cross...'
        make -C mpy-cross -j\$(nproc)
        echo '[*] Build ESP32...'
        make -C ports/esp32 BOARD=ESP32_GENERIC -j\$(nproc)
    "

# ── Copier le firmware mergé ───────────────────────────────────────────────────

MERGED="$BUILD_DIR/ports/esp32/build-ESP32_GENERIC/firmware.bin"
APP="$BUILD_DIR/ports/esp32/build-ESP32_GENERIC/micropython.bin"
OUT_MERGED="$OUT_DIR/micropython-esp32-custom-wifi.bin"
OUT_APP="$OUT_DIR/micropython-app-patched.bin"

[ -f "$MERGED" ] || die "Binaire introuvable après build : $MERGED"
cp "$MERGED" "$OUT_MERGED"
log "Firmware mergé (bootloader+app) : firmware/micropython-esp32-custom-wifi.bin"

# ── Patch binaire : bypasse ieee80211_raw_frame_sanity_check ──────────────────

log "Application du bypass deauth (patch binaire)..."
PATCH_SCRIPT="$(cd "$(dirname "$0")" && pwd)/patch_deauth_bypass.py"
python3 "$PATCH_SCRIPT"
log "APP patchée : firmware/micropython-app-patched.bin"
log "Taille app : $(du -h "$OUT_APP" | cut -f1)"

# ── Flash optionnel ────────────────────────────────────────────────────────────

echo ""
read -rp "Flasher maintenant sur $PORT ? [o/N] " answer || true
if [[ "$answer" =~ ^[oO]$ ]]; then
    log "Effacement de la flash..."
    python3 -m esptool --port "$PORT" --baud 460800 erase-flash
    log "Flash du firmware mergé (bootloader + app)..."
    python3 -m esptool --port "$PORT" --baud 460800 \
        write-flash -z 0x1000 "$OUT_MERGED"
    log "Flash de l'APP patchée (deauth bypass)..."
    python3 -m esptool --port "$PORT" --baud 460800 \
        write-flash -z 0x10000 "$OUT_APP"
    log "Flash terminé — l'ESP32 redémarre avec injection Deauth activée"
else
    warn "Flash ignoré."
    echo "  Flash complet (première installation) :"
    echo "  python3 -m esptool --port $PORT --baud 460800 erase-flash"
    echo "  python3 -m esptool --port $PORT --baud 460800 write-flash -z 0x1000 $OUT_MERGED"
    echo "  python3 -m esptool --port $PORT --baud 460800 write-flash -z 0x10000 $OUT_APP"
    echo ""
    echo "  Mise à jour app seule (si bootloader déjà flashé) :"
    echo "  python3 -m esptool --port $PORT --baud 460800 write-flash -z 0x10000 $OUT_APP"
fi
