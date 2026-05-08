# Rapport de Laboratoire — Audit de Sécurité WiFi sur ESP32

**Auteur :** HERIMANATSOA Odilon  
**Date :** 08 mai 2026  
**Module :** Sécurité des réseaux sans fil  
**Cadre :** Travaux pratiques — Environnement isolé / réseau personnel

---

## Table des matières

1. [Introduction](#1-introduction)
2. [Objectifs du laboratoire](#2-objectifs-du-laboratoire)
3. [Outils utilisés](#3-outils-utilisés)
4. [Architecture du lab](#4-architecture-du-lab)
5. [Manipulations et résultats](#5-manipulations-et-résultats)
   - 5.1 [Scanner WiFi](#51-scanner-wifi)
   - 5.2 [Capture du handshake WPA2 (airodump-ng)](#52-capture-du-handshake-wpa2--airodump-ng)
   - 5.3 [Capture PMKID (hcxdumptool)](#53-capture-pmkid--hcxdumptool)
   - 5.4 [Extraction du hash (hcxpcapngtool)](#54-extraction-du-hash--hcxpcapngtool)
   - 5.5 [Attaque Deauth](#55-attaque-deauth)
   - 5.6 [Beacon Spam](#56-beacon-spam)
   - 5.7 [Evil Twin + portail captif](#57-evil-twin--portail-captif)
   - 5.8 [Crack WPA2 avec hashcat](#58-crack-wpa2-avec-hashcat)
   - 5.9 [Packet Sniffer & streaming vers Kali](#59-packet-sniffer--streaming-vers-kali)
6. [Conclusion](#6-conclusion)

---

## 1. Introduction

La sécurité des réseaux sans fil représente un enjeu majeur dans les infrastructures modernes. Le protocole 802.11 (WiFi), malgré les évolutions apportées par WPA2 et WPA3, reste exposé à plusieurs catégories d'attaques : désauthentification forcée, capture de handshake, usurpation de point d'accès (Evil Twin) ou encore exploitation du mécanisme PMKID.

Ce laboratoire a pour cadre la mise en œuvre pratique d'un outil d'audit WiFi portable, reposant sur un microcontrôleur **ESP32 WROOM** flashé avec un firmware MicroPython personnalisé, piloté depuis une interface web moderne tournant sur une machine sous **Kali Linux**. L'ensemble des manipulations a été réalisé sur un réseau personnel, dans un environnement entièrement isolé, à des fins strictement éducatives et défensives.

---

## 2. Objectifs du laboratoire

- Comprendre le fonctionnement des trames 802.11 (Beacon, Probe, Auth, Deauth, EAPOL).
- Mettre en œuvre un scanner WiFi actif pour identifier les réseaux environnants (SSID, BSSID, canal, chiffrement, RSSI).
- Capturer un handshake WPA2 et un hash PMKID à l'aide d'outils spécialisés.
- Réaliser une attaque par désauthentification pour forcer la reconnexion d'un client.
- Tester un scénario Evil Twin avec portail captif pour illustrer le risque d'hameçonnage WiFi.
- Tenter de retrouver une clé WPA2 par attaque par dictionnaire avec hashcat.
- Analyser les trames capturées avec Wireshark afin de comprendre les échanges au niveau protocolaire.

---

## 3. Outils utilisés

| Outil | Rôle | Version / Plateforme |
|---|---|---|
| **ESP32 WROOM** | Sonde WiFi portable (scan, injection, promiscuous) | Dual Core 240 MHz, 4 MB Flash |
| **MicroPython custom** | Firmware exposant les API bas niveau ESP-IDF | v1.25.0 + patch injection |
| **mpremote** | Communication série avec l'ESP32 | pip — Python 3 |
| **esptool** | Flash du firmware sur l'ESP32 | pip — Python 3 |
| **Flask (webui.py)** | Interface web de contrôle (port 8080) | Python 3 |
| **airmon-ng** | Passage de l'interface WiFi hôte en mode monitor | Suite aircrack-ng |
| **airodump-ng** | Capture passive de trames 802.11 / handshake WPA2 | Suite aircrack-ng |
| **aireplay-ng** | Envoi de trames de désauthentification depuis l'hôte | Suite aircrack-ng |
| **hcxdumptool** | Capture ciblée de PMKID / EAPOL | hcxtools |
| **hcxpcapngtool** | Conversion de captures `.pcapng` en hash `.hc22000` | hcxtools |
| **hashcat** | Crack par dictionnaire des hashs WPA2 | GPU / CPU |
| **Wireshark** | Analyse protocolaire des captures `.pcap` | v4.x Linux |
| **Docker + ESP-IDF v5.2** | Build du firmware custom (mode promiscuous + injection) | Docker |

---

## 4. Architecture du lab

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

L'ESP32 est connecté en USB à la machine Kali. Il est contrôlé via le port série `/dev/ttyUSB0` (baudrate 115200) par `mpremote`, ou via l'interface web Flask accessible sur `http://localhost:8080`. Les captures brutes (`.pcap`, `.hc22000`) sont stockées dans le répertoire `captures/` de la machine hôte.

---

## 5. Manipulations et résultats

### 5.1 Scanner WiFi

**Commande utilisée :**

```python
# Depuis le REPL MicroPython (via mpremote)
from lib.wifi_scanner import scan
nets = scan()
```

Ou depuis l'interface web → onglet **Scanner**.

**Résultat :**

![Scanner WiFi — tableau des réseaux détectés](images%20/page%20scaner%20.png)

*Le scanner affiche l'ensemble des points d'accès 802.11 détectés à portée, avec pour chaque réseau : le SSID, le BSSID (adresse MAC de l'AP), le canal, le niveau de signal (RSSI en dBm) et le type de chiffrement.*

> Le tableau révèle plusieurs réseaux WPA2, confirmant que ce protocole reste dominant dans les environnements domestiques. Le RSSI permet d'évaluer la distance approximative de chaque AP ; des valeurs proches de -30 dBm indiquent une proximité physique importante, tandis que les valeurs inférieures à -80 dBm signalent des cibles hors de portée effective pour une attaque ou une capture fiable.

---

### 5.2 Capture du handshake WPA2 — airodump-ng

**Commandes utilisées :**

```bash
# Passage en mode monitor
sudo airmon-ng check kill
sudo airmon-ng start wlan0

# Capture ciblée sur le BSSID de la cible (canal 6)
sudo airodump-ng -c 6 --bssid <BSSID_CIBLE> -w captures/airbox wlan0mon
```

**Résultat :**

<!-- INSÉRER ICI : capture d'écran du terminal airodump-ng avec le message WPA handshake -->
`[CAPTURE_AIRODUMP — à insérer]`

> Airodump-ng affiche en temps réel les trames capturées sur le canal sélectionné, avec la liste des clients associés à l'AP cible. Lorsque le message `WPA handshake: <BSSID>` apparaît en haut à droite du terminal, cela confirme qu'un échange EAPOL en 4 étapes a bien été capturé entre un client et l'AP.

> Le fichier `airbox-01.cap` généré (3,1 Mo) contient l'ensemble des trames 802.11 capturées. C'est ce fichier qui sera transmis à hashcat après extraction du hash, ou analysé directement dans Wireshark pour visualiser les messages EAPOL (ANonce, SNonce + MIC).

---

### 5.3 Capture PMKID — hcxdumptool

**Commandes utilisées :**

```bash
# Capture PMKID ciblée (quelques secondes suffisent)
sudo hcxdumptool -i wlan0mon -c 6 \
    -w captures/pmkid.pcapng --rds=2 -t 60
```

**Résultat :**

<!-- INSÉRER ICI : capture d'écran du terminal hcxdumptool en cours de capture -->
`[CAPTURE_HCXDUMPTOOL — à insérer]`

> Contrairement à la capture de handshake qui nécessite qu'un client se connecte (ou soit déconnecté de force), l'attaque PMKID est initiée directement vers l'AP sans client présent. L'outil `hcxdumptool` envoie des trames d'association et tente d'extraire le PMKID contenu dans le premier message EAPOL de l'AP.

> Le fichier `pmkid.pcapng` (13 Ko) et `pmkid_9cda36ab1cb0.pcap` (149 Ko) contiennent les trames brutes. Le PMKID est calculé à partir de la PMK, du BSSID et de la MAC de la station : `PMKID = HMAC-SHA1-128(PMK, "PMK Name" || BSSID || STA_MAC)`. Sa présence dans la capture suffit à lancer une attaque par dictionnaire sans nécessiter d'échange complet.

---

### 5.4 Extraction du hash — hcxpcapngtool

**Commande utilisée :**

```bash
hcxpcapngtool -o captures/airbox.hc22000 captures/airbox-01.cap
# ou depuis le pcapng PMKID :
hcxpcapngtool -o captures/pmkid_9cda36ab1cb0.hc22000 captures/pmkid_9cda36ab1cb0.pcap
```

**Résultat :**

<!-- INSÉRER ICI : capture d'écran du terminal montrant la conversion et le contenu du fichier .hc22000 -->
`[CAPTURE_HCXPCAPNG — à insérer]`

> L'outil `hcxpcapngtool` extrait des captures brutes les informations nécessaires au crack : le type de hash (PMKID ou EAPOL), le BSSID, la MAC de la station, et la valeur à attaquer. Le format de sortie `.hc22000` est directement reconnu par hashcat en mode `-m 22000`, qui unifie le crack PMKID et EAPOL depuis hashcat 6.x.

> Le fichier `airbox.hc22000` (412 octets) contient une ligne par hash extrait. La présence de ce fichier confirme qu'au moins un PMKID ou un handshake exploitable a été capturé avec succès sur le réseau cible.

---

### 5.5 Attaque Deauth

**Commande utilisée (depuis l'interface web ou REPL) :**

```python
# Via REPL MicroPython sur l'ESP32
from lib.deauth import deauth_broadcast, deauth_client

# Déconnecter tous les clients de l'AP
deauth_broadcast('<BSSID_AP>', count=200)

# Déconnecter un client précis
deauth_client('<BSSID_AP>', '<MAC_CLIENT>', count=100)
```

Ou depuis l'interface web → onglet **Deauth**.

**Résultat :**

<!-- INSÉRER ICI : capture d'écran de l'interface web onglet Deauth avec les paramètres et l'exécution -->
`[CAPTURE_DEAUTH — à insérer]`

> L'attaque de désauthentification exploite une faille de conception du standard 802.11 : les trames de type Deauthentication (FC[0]=0xC0, reason code 7) ne sont pas authentifiées, ce qui permet à n'importe quel acteur de les émettre en usurpant l'adresse MAC de l'AP. En envoyant ces trames au(x) client(s), on force leur déconnexion du réseau.

> Cette technique est utilisée en complément de la capture de handshake : en déconnectant un client associé, on provoque sa reconnexion, ce qui déclenche un échange EAPOL 4-way visible par airodump-ng. Sur les réseaux modernes protégés par 802.11w (Management Frame Protection), cette attaque est bloquée au niveau des trames de gestion unicast.

---

### 5.6 Beacon Spam

**Commande utilisée :**

```python
# Via REPL MicroPython
from lib.beacon_spam import spam_random, spam_fr, spam_clone

spam_random(channel=6)           # Dizaines de SSIDs aléatoires
spam_fr(channel=1)               # SSIDs imitant des opérateurs français
spam_clone('NomCible', channel=6) # Cloner un SSID existant
```

Ou depuis l'interface web → onglet **Beacon Spam**.

**Résultat :**

<!-- INSÉRER ICI : capture d'écran du scan WiFi montrant les faux réseaux générés -->
`[CAPTURE_BEACON_SPAM — à insérer]`

> Le beacon spam consiste à émettre des trames Beacon (FC[0]=0x80) avec des SSID et BSSID forgés à haute fréquence. Chaque trame annonce un faux point d'accès, faisant apparaître des dizaines de réseaux inexistants dans la liste WiFi de tout appareil à portée. Cette technique illustre la facilité avec laquelle l'espace radio peut être saturé.

> Outre le caractère perturbateur (saturation de la liste WiFi), le beacon spam est souvent utilisé comme couverture lors d'une attaque Evil Twin : en noyant la liste de faux réseaux, la victime peine à identifier le vrai AP parmi les leurres, augmentant les chances qu'elle se connecte au faux AP.

---

### 5.7 Evil Twin + portail captif

**Commande utilisée :**

```python
# Via REPL MicroPython
from lib.evil_twin import start, show_captured
from lib.wifi_scanner import scan, select

nets  = scan()
cible = select(nets)

# Démarrage Evil Twin + deauth de l'AP réel
start(cible['ssid'], channel=cible['ch'], deauth_ap_mac=cible['bssid'])

# Afficher les credentials capturés
show_captured()
```

Ou depuis l'interface web → onglet **Evil Twin**.

**Résultat :**

<!-- INSÉRER ICI : capture d'écran du portail captif affiché à la victime -->
`[CAPTURE_EVIL_TWIN_PORTAIL — à insérer]`

<!-- INSÉRER ICI : capture d'écran des credentials capturés dans l'interface web -->
`[CAPTURE_EVIL_TWIN_CREDENTIALS — à insérer]`

> L'attaque Evil Twin crée un point d'accès sans fil avec le même SSID que la cible, sans mot de passe (open), sur le même canal. Combinée à une attaque Deauth sur l'AP légitime, elle pousse les clients déconnectés à s'associer au faux AP. Un serveur DNS est activé en parallèle pour rediriger toutes les requêtes vers un portail captif local.

> Lorsque la victime ouvre son navigateur, elle est redirigée vers une page imitant une page de connexion (simulant une mise à jour firmware ou une re-authentification). Les identifiants saisis sont journalisés côté ESP32. Cette démonstration illustre la dangerosité des réseaux ouverts et l'importance de vérifier l'authenticité d'un portail captif avant de saisir des informations.

---

### 5.8 Crack WPA2 avec hashcat

**Commande utilisée :**

```bash
# Attaque par dictionnaire sur le hash capturé
hashcat -m 22000 captures/airbox.hc22000 /usr/share/wordlists/rockyou.txt

# Vérifier le résultat
hashcat -m 22000 captures/airbox.hc22000 --show
```

**Résultat :**

<!-- INSÉRER ICI : capture d'écran du terminal hashcat avec le mot de passe trouvé (ou la tentative) -->
`[CAPTURE_HASHCAT — à insérer]`

> Hashcat attaque le hash WPA2 en mode `-m 22000` (PMKID + EAPOL unifié). Pour chaque mot de passe du dictionnaire, il recalcule le MIC (Message Integrity Code) ou le PMKID et compare le résultat avec la valeur capturée. Si le mot de passe est présent dans le dictionnaire `rockyou.txt` (~14 millions d'entrées), il est retrouvé en quelques secondes à quelques minutes selon le matériel disponible.

> Le fichier `airbox.pot` (vide ici) est le fichier de résultats de hashcat : son contenu vide indique que le mot de passe cible ne figure pas dans `rockyou.txt`, démontrant l'efficacité d'un mot de passe non-trivial face aux attaques par dictionnaire. Cela souligne l'importance d'utiliser des mots de passe longs, aléatoires et uniques pour sécuriser un réseau WPA2.

---

### 5.9 Packet Sniffer & streaming vers Kali

**Commandes utilisées :**

```bash
# Sur Kali — démarrer le receiver TCP
python3 tools/receiver.py --port 9999 --out captures/
```

```python
# Sur l'ESP32 — connecter et streamer
from lib.streaming import connect_ap, start

connect_ap('NomHotspot', 'motdepasse')
start(duration=120, channel=6)  # 2 min sur canal 6
```

Puis analyse dans Wireshark :

```bash
wireshark captures/capture_*.pcap
```

**Résultat :**

<!-- INSÉRER ICI : capture d'écran de Wireshark avec les trames 802.11 capturées -->
`[CAPTURE_WIRESHARK — à insérer]`

> Le mode promiscuous activé via `esp.wifi_set_promiscuous()` (API exposée uniquement par le firmware custom) permet à l'ESP32 de capturer toutes les trames 802.11 sur le canal sélectionné, y compris celles qui ne lui sont pas destinées. Les trames sont envoyées brutes via TCP vers le `receiver.py` qui les encapsule au format PCAP.

> L'analyse Wireshark révèle la structure complète des trames 802.11 : Beacon frames émises par les APs, Probe Requests des appareils cherchant leurs réseaux enregistrés, et trames Data contenant potentiellement des échanges EAPOL. Cette visibilité illustre pourquoi les communications WiFi non chiffrées (ou mal chiffrées) constituent une surface d'attaque significative.

---

## 6. Conclusion

Ce laboratoire a permis d'explorer de manière pratique et progressive les principales vulnérabilités du standard 802.11 WPA2. À travers sept types de manipulations distinctes, nous avons démontré que :

- La **capture de handshake** et du **PMKID** est réalisable en quelques dizaines de secondes avec des outils libres (`hcxdumptool`, `airodump-ng`), dès lors qu'on dispose d'une interface WiFi en mode monitor.
- L'**attaque de désauthentification** est triviale à mettre en œuvre du fait de l'absence d'authentification des trames de gestion 802.11, et reste efficace sur la majorité des réseaux domestiques (sans 802.11w activé).
- L'attaque **Evil Twin** avec portail captif constitue l'une des menaces les plus redoutables pour l'utilisateur final, car elle combine ingénierie sociale et exploitation protocolaire sans nécessiter de crack cryptographique.
- La **robustesse du mot de passe** WPA2 reste la principale défense contre le crack par dictionnaire : un mot de passe long et aléatoire résiste efficacement à rockyou.txt et aux attaques similaires.
- Le **mode promiscuous** sur ESP32, rendu possible par un firmware personnalisé, transforme un microcontrôleur à moins de 5 € en sonde d'audit WiFi portable et silencieuse.

Sur le plan défensif, ces manipulations mettent en évidence plusieurs bonnes pratiques : activer la **protection des trames de gestion (802.11w/MFP)**, utiliser des **mots de passe WPA2 forts et uniques**, se méfier des **portails captifs inattendus**, et préférer un **VPN** sur les réseaux dont on ne contrôle pas l'infrastructure.

L'ensemble de ces travaux a été réalisé dans un cadre strictement contrôlé, sur des équipements personnels, dans le seul but de comprendre les mécanismes d'attaque afin de mieux les contrer.

---

*Rapport généré dans le cadre d'un TP de sécurité des réseaux — usage éducatif et défensif uniquement.*t