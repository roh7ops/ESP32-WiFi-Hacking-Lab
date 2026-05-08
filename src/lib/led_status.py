"""
LED status — ESP32 WiFi Lab
Par défaut : LED built-in GPIO 2 (ESP32 DevKit v1, active HIGH)

Pour activer NeoPixel WS2812 (ESP32-C3 Super Mini, etc.) :
  - mettre _NEOPIXEL = True
  - régler _RGB_PIN selon le board (8 pour ESP32-C3 Super Mini)
"""

from machine import Pin, Timer

# ── Configuration (à adapter selon le board) ────────────────────────
_NEOPIXEL = False   # False = LED simple GPIO ; True = WS2812 NeoPixel
_RGB_PIN  = 8       # pin NeoPixel (ignoré si _NEOPIXEL = False)
_LED_PIN  = 2       # GPIO LED built-in ESP32 DevKit v1
_LED_LOW  = False   # True si LED câblée active-LOW (rare sur DevKit v1)

# ── Init ─────────────────────────────────────────────────────────────
_tim = Timer(-1)
_bv  = [False, 0, 0, 0]   # [phase, r, g, b]

if _NEOPIXEL:
    try:
        from neopixel import NeoPixel as _NP
        _np  = _NP(Pin(_RGB_PIN, Pin.OUT), 1)
        _led = None
    except Exception:
        _NEOPIXEL = False
        _np  = None
        _led = Pin(_LED_PIN, Pin.OUT, value=int(_LED_LOW))
else:
    _np  = None
    _led = Pin(_LED_PIN, Pin.OUT, value=int(_LED_LOW))

# ── Primitives ────────────────────────────────────────────────────────

def _c(r, g, b):
    if _np:
        _np[0] = (r, g, b); _np.write()
    elif _led is not None:
        on = bool(r or g or b)
        _led.value(int((not on) if _LED_LOW else on))

def _stop():
    _tim.deinit()

def _solid(r, g, b):
    _stop(); _c(r, g, b)

def _blink(r, g, b, ms):
    _stop()
    _bv[0] = False; _bv[1] = r; _bv[2] = g; _bv[3] = b
    def _cb(t):
        _bv[0] = not _bv[0]
        _c(_bv[1], _bv[2], _bv[3]) if _bv[0] else _c(0, 0, 0)
    _tim.init(period=ms, mode=Timer.PERIODIC, callback=_cb)

# ── États publics ─────────────────────────────────────────────────────
#   LED simple  → clignotement avec la vitesse indiquée (on/off)
#   NeoPixel    → même comportement mais avec couleurs

def off():       _stop(); _c(0, 0, 0)          # éteint
def idle():      _solid(1, 1, 1)               # LED fixe faible (veille)
def scanning():  _blink(1, 1, 1, 120)          # rapide (scan WiFi)
def capturing(): _blink(1, 1, 1, 350)          # moyen  (capture EAPOL)
def cracking():  _blink(1, 1, 1, 80)           # très rapide (hashcat)
def found():     _solid(1, 1, 1); _stop()      # fixe brillant (trouvé!)
def error():     _blink(1, 1, 1, 600)          # lent (erreur)

# Variantes NeoPixel — utilisées automatiquement si _NEOPIXEL = True
def _rgb_idle():      _solid(0, 0, 10)
def _rgb_scanning():  _blink(0, 0, 50, 120)
def _rgb_capturing(): _blink(0, 30, 30, 350)
def _rgb_cracking():  _blink(50, 15, 0, 80)
def _rgb_found():     _solid(0, 60, 0)
def _rgb_error():     _blink(50, 0, 0, 600)

# Réaffectation si RGB dispo
if _NEOPIXEL and _np:
    idle      = _rgb_idle
    scanning  = _rgb_scanning
    capturing = _rgb_capturing
    cracking  = _rgb_cracking
    found     = _rgb_found
    error     = _rgb_error
