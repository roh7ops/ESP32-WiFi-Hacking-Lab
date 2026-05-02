# Versions
FIRMWARE_VERSION = "1.25.0"
PROJECT_VERSION  = "0.1.0"

# Port série (utilisé par les outils hôte)
SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE   = 115200

# WiFi — scan et channel hopping
CHANNELS     = list(range(1, 14))   # canaux 1 à 13 (Europe)
HOP_INTERVAL = 200                  # ms par canal en mode scan
DWELL_TIME   = 3000                 # ms sur un canal cible en mode lock

# Streaming vers Kali (TCP)
STREAM_HOST   = "192.168.43.1"      # IP de Kali sur le hotspot Android
STREAM_PORT   = 9999
STREAM_ENABLE = False               # passer à True pour activer le streaming

# Evil Twin — serveur HTTP captif
EVIL_TWIN_IP   = "192.168.4.1"
EVIL_TWIN_PORT = 80

# Debug — affiche les trames brutes dans display.warn()
DEBUG = True
