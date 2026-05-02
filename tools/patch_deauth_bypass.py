#!/usr/bin/env python3
"""
Patch post-build pour bypasser ieee80211_raw_frame_sanity_check dans micropython.bin.

ESP-IDF v5.x bloque esp_wifi_80211_tx pour Deauth/Disassoc/Auth via
ieee80211_raw_frame_sanity_check. Ce script :
  1. Cherche le pattern de ieee80211_raw_frame_sanity_check dans micropython.bin
  2. Le remplace par notre stub "return ESP_OK" (entry/movi.n/retw.n = 7 bytes)
  3. Recalcule le SHA256 de l'image APP (requis par ESP-IDF v5)
  4. Flash uniquement l'APP à 0x10000 (bootloader/partition table inchangés)

Utilisation :
  python3 patch_deauth_bypass.py [--flash]
"""

import hashlib, struct, subprocess, sys
from pathlib import Path

BUILD    = Path("/run/media/roh/Sitoky140/Hacking/build-micropython/ports/esp32/build-ESP32_GENERIC")
ELF      = BUILD / "micropython.elf"
APP_BIN  = BUILD / "micropython.bin"
OUT_APP  = Path("/run/media/roh/Sitoky140/Hacking/Wifi Hacking/firmware/micropython-app-patched.bin"
                )
PORT     = "/dev/ttyUSB0"

TARGET_SYM = "ieee80211_raw_frame_sanity_check"
STUB_SYM   = "__wrap_ieee80211_raw_frame_sanity_check"


def nm_symbol(elf: Path, sym: str) -> int | None:
    out = subprocess.check_output(["nm", str(elf)], stderr=subprocess.DEVNULL).decode()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] == sym and parts[1].upper() == "T":
            return int(parts[0], 16)
    return None


def parse_load_segments(elf_data: bytes):
    e_phoff   = struct.unpack_from("<I", elf_data, 28)[0]
    e_phentsz = struct.unpack_from("<H", elf_data, 42)[0]
    e_phnum   = struct.unpack_from("<H", elf_data, 44)[0]
    segs = []
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsz
        p_type   = struct.unpack_from("<I", elf_data, o)[0]
        if p_type != 1:
            continue
        p_offset = struct.unpack_from("<I", elf_data, o +  4)[0]
        p_vaddr  = struct.unpack_from("<I", elf_data, o +  8)[0]
        p_filesz = struct.unpack_from("<I", elf_data, o + 16)[0]
        segs.append((p_vaddr, p_filesz, p_offset))
    return segs


def vaddr_to_elf_offset(segs, vaddr: int) -> int | None:
    for p_vaddr, p_filesz, p_offset in segs:
        if p_vaddr <= vaddr < p_vaddr + p_filesz:
            return p_offset + (vaddr - p_vaddr)
    return None


def recalculate_sha256(data: bytearray) -> bytearray:
    """
    ESP32 app image : les 32 derniers octets sont le SHA256 de tout
    ce qui précède (si CONFIG_APP_RETRIEVE_LEN_ELF_SHA=y).
    Recalcule et remplace le hash en fin de fichier.
    """
    if len(data) < 32:
        return data
    h = hashlib.sha256(bytes(data[:-32])).digest()
    data[-32:] = h
    return data


def main():
    do_flash = "--flash" in sys.argv

    elf_data = bytearray(ELF.read_bytes())
    segs     = parse_load_segments(bytes(elf_data))

    target_vaddr = nm_symbol(ELF, TARGET_SYM)
    stub_vaddr   = nm_symbol(ELF, STUB_SYM)

    if not target_vaddr:
        print(f"[x] Symbole introuvable dans l'ELF : {TARGET_SYM}")
        sys.exit(1)
    if not stub_vaddr:
        print(f"[x] Symbole introuvable dans l'ELF : {STUB_SYM}")
        sys.exit(1)

    stub_off = vaddr_to_elf_offset(segs, stub_vaddr)
    if stub_off is None:
        print(f"[x] Impossible de localiser {STUB_SYM} dans l'ELF")
        sys.exit(1)

    stub_bytes = bytes(elf_data[stub_off : stub_off + 7])
    print(f"[*] Stub '{STUB_SYM}' (VMA=0x{stub_vaddr:08x}) : {stub_bytes.hex(' ')}")

    # ── Lire micropython.bin et localiser le pattern ──────────────────────────
    app_data = bytearray(APP_BIN.read_bytes())
    pattern  = bytes(elf_data[vaddr_to_elf_offset(segs, target_vaddr) :
                               vaddr_to_elf_offset(segs, target_vaddr) + 7])

    idx = app_data.find(pattern)
    if idx == -1:
        print(f"[x] Pattern introuvable dans micropython.bin : {pattern.hex(' ')}")
        print(f"    VMA=0x{target_vaddr:08x} — vérifiez que micropython.bin correspond à l'ELF")
        sys.exit(1)

    print(f"[*] Pattern trouvé dans micropython.bin à l'offset 0x{idx:x}")
    print(f"    Octets avant patch : {app_data[idx:idx+7].hex(' ')}")

    if app_data[idx:idx+7] == stub_bytes:
        print("[!] Déjà patché — rien à faire")
    else:
        app_data[idx : idx+7] = stub_bytes
        print(f"    Octets après patch  : {app_data[idx:idx+7].hex(' ')}")

        # Recalculer le SHA256 de l'image
        app_data = recalculate_sha256(app_data)
        print(f"[+] SHA256 recalculé")

    OUT_APP.write_bytes(bytes(app_data))
    print(f"[+] APP patchée : {OUT_APP} ({OUT_APP.stat().st_size} octets)")

    if do_flash:
        print(f"[*] Flash de l'APP à 0x10000 sur {PORT}...")
        cmd = [
            "python3", "-m", "esptool",
            "--port", PORT, "--baud", "460800",
            "write-flash", "-z", "0x10000", str(OUT_APP),
        ]
        result = subprocess.run(cmd)
        if result.returncode == 0:
            print("[+] Flash terminé — l'ESP32 redémarre")
        else:
            print("[x] Erreur flash")
            sys.exit(1)
    else:
        print(f"\n  Pour flasher :")
        print(f"  python3 -m esptool --port {PORT} --baud 460800 write-flash -z 0x10000 {OUT_APP}")


if __name__ == "__main__":
    main()
