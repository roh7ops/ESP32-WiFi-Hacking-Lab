#!/usr/bin/env python3
"""
Modifie ports/esp32/modesp.c pour exposer trois fonctions WiFi esp-idf :
  - esp.wifi_set_promiscuous(True/False)  — active/désactive la capture
  - esp.wifi_get_pkt()                   — lit le prochain paquet capturé (bytes ou None)
  - esp.wifi_send_pkt_freedom(buf, seq)  — injecte une trame 802.11 brute

Bypasse aussi ieee80211_raw_frame_sanity_check via linker --wrap pour permettre
l'injection de trames Deauth/Disassoc/Auth (bloquées en ESP-IDF v5.x).

Architecture : ring buffer C (pas de malloc dans le callback), polling depuis Python.
"""

import sys
from pathlib import Path

TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else \
         Path("/run/media/roh/Sitoky140/Hacking/build-micropython/ports/esp32/modesp.c")

# ── Marqueur exact dans modesp.c v1.25.0 ─────────────────────────────────────
TABLE_MARKER = "static const mp_rom_map_elem_t esp_module_globals_table[]"

# ── Includes à ajouter ────────────────────────────────────────────────────────
INCLUDES = """\
#include <string.h>
#include "esp_wifi.h"
#include "esp_wifi_types.h"
"""

# ── Fonctions C à injecter avant la table des globals ─────────────────────────
FUNCTIONS = """
/* ── WiFi hacking bindings ─────────────────────────────────────────────────── */

#define _PKT_BUF_COUNT  16
#define _PKT_MAX_LEN    400

typedef struct { uint8_t data[_PKT_MAX_LEN]; uint16_t len; } _pkt_t;

static _pkt_t             _pkt_buf[_PKT_BUF_COUNT];
static volatile int       _pkt_head   = 0;
static volatile int       _pkt_tail   = 0;
static volatile int       _promisc_on = 0;

static void _promisc_cb(void *buf, wifi_promiscuous_pkt_type_t type) {
    if (!_promisc_on) return;
    wifi_promiscuous_pkt_t *p = (wifi_promiscuous_pkt_t *)buf;
    uint16_t len = p->rx_ctrl.sig_len;
    if (len > _PKT_MAX_LEN) len = _PKT_MAX_LEN;
    int next = (_pkt_tail + 1) % _PKT_BUF_COUNT;
    if (next == _pkt_head) return;  /* buffer plein */
    memcpy(_pkt_buf[_pkt_tail].data, p->payload, len);
    _pkt_buf[_pkt_tail].len = len;
    _pkt_tail = next;
}

static mp_obj_t esp_wifi_set_promiscuous_wrap(mp_obj_t enable) {
    _promisc_on = mp_obj_is_true(enable);
    if (_promisc_on) {
        _pkt_head = _pkt_tail = 0;
        esp_wifi_set_promiscuous_rx_cb(_promisc_cb);
    }
    esp_wifi_set_promiscuous(_promisc_on);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(esp_wifi_set_promiscuous_obj,
                                   esp_wifi_set_promiscuous_wrap);

static mp_obj_t esp_wifi_get_pkt(void) {
    if (_pkt_head == _pkt_tail) return mp_const_none;
    _pkt_t *e = &_pkt_buf[_pkt_head];
    mp_obj_t data = mp_obj_new_bytes(e->data, e->len);
    _pkt_head = (_pkt_head + 1) % _PKT_BUF_COUNT;
    return data;
}
static MP_DEFINE_CONST_FUN_OBJ_0(esp_wifi_get_pkt_obj, esp_wifi_get_pkt);

static mp_obj_t esp_wifi_send_pkt_freedom_wrap(mp_obj_t buf_obj, mp_obj_t seq_obj) {
    mp_buffer_info_t bi;
    mp_get_buffer_raise(buf_obj, &bi, MP_BUFFER_READ);
    esp_err_t err = esp_wifi_80211_tx(WIFI_IF_STA, bi.buf, bi.len,
                                       mp_obj_is_true(seq_obj));
    if (err != ESP_OK) mp_raise_OSError(MP_EIO);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_2(esp_wifi_send_pkt_freedom_obj,
                                   esp_wifi_send_pkt_freedom_wrap);

/*
 * Bypass de ieee80211_raw_frame_sanity_check via linker --wrap.
 * ESP-IDF v5.x refuse d'injecter Deauth(0xC0)/Disassoc(0xA0)/Auth(0xB0)
 * via esp_wifi_80211_tx en appelant cette fonction de vérification.
 * Notre wrapper retourne toujours ESP_OK pour lever cette restriction.
 */
__attribute__((used))
esp_err_t __wrap_ieee80211_raw_frame_sanity_check(
        wifi_interface_t ifx, const void *buffer, int len, bool en_sys_seq) {
    return ESP_OK;
}

/* ── Fin WiFi hacking bindings ─────────────────────────────────────────────── */
"""

# ── Entrées à ajouter dans la table des globals ───────────────────────────────
TABLE_ENTRIES = """\
    { MP_ROM_QSTR(MP_QSTR_wifi_set_promiscuous),  MP_ROM_PTR(&esp_wifi_set_promiscuous_obj) },
    { MP_ROM_QSTR(MP_QSTR_wifi_get_pkt),          MP_ROM_PTR(&esp_wifi_get_pkt_obj) },
    { MP_ROM_QSTR(MP_QSTR_wifi_send_pkt_freedom), MP_ROM_PTR(&esp_wifi_send_pkt_freedom_obj) },
"""

# ── Marqueur/ajout dans CMakeLists.txt ───────────────────────────────────────
CMAKE_MARKER = "# Include main IDF cmake file."
CMAKE_WRAP   = '# Bypass ieee80211_raw_frame_sanity_check pour injection Deauth/Auth/Disassoc\n' \
               'set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} ' \
               '-Wl,--undefined=__wrap_ieee80211_raw_frame_sanity_check ' \
               '-Wl,--wrap=ieee80211_raw_frame_sanity_check")\n\n'

# ── Application ───────────────────────────────────────────────────────────────

def patch_modesp(path: Path):
    if not path.exists():
        print(f"[x] Fichier introuvable : {path}")
        sys.exit(1)

    src = path.read_text()

    if "wifi_send_pkt_freedom" in src:
        print("[!] modesp.c déjà patché — rien à faire")
        return

    if TABLE_MARKER not in src:
        print(f"[x] Marqueur introuvable : '{TABLE_MARKER}'")
        for line in src.splitlines():
            if "globals_table" in line:
                print("   ", line)
        sys.exit(1)

    # 1. Ajouter les includes après la première ligne #include
    first_inc = src.index("#include")
    eol       = src.index("\n", first_inc)
    src = src[:eol + 1] + INCLUDES + src[eol + 1:]

    # 2. Injecter les fonctions juste avant la table
    idx = src.index(TABLE_MARKER)
    src = src[:idx] + FUNCTIONS + src[idx:]

    # 3. Ajouter les entrées dans la table (avant le PREMIER }; après TABLE_MARKER)
    table_start = src.index(TABLE_MARKER)
    closing = src.index("};", table_start)
    src = src[:closing] + TABLE_ENTRIES + src[closing:]

    path.write_text(src)
    print(f"[+] modesp.c patché : {path}")


def patch_cmake(path: Path):
    if not path.exists():
        print(f"[x] CMakeLists.txt introuvable : {path}")
        return

    src = path.read_text()

    if "--wrap=ieee80211_raw_frame_sanity_check" in src:
        print("[!] CMakeLists.txt déjà patché — rien à faire")
        return

    if CMAKE_MARKER not in src:
        print(f"[x] Marqueur CMake introuvable : '{CMAKE_MARKER}'")
        return

    idx = src.index(CMAKE_MARKER)
    src = src[:idx] + CMAKE_WRAP + src[idx:]
    path.write_text(src)
    print(f"[+] CMakeLists.txt patché : {path}")


if __name__ == "__main__":
    base = TARGET.parent

    patch_modesp(TARGET)
    patch_cmake(base / "CMakeLists.txt")
