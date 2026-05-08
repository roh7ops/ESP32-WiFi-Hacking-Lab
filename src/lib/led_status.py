"""
Indicateur LED de statut — ESP32 WiFi Lab
Auto-détecte NeoPixel WS2812 (RGB) ou LED simple GPIO 2.

États disponibles (appelables directement) :
  off()       — éteint
  idle()      — bleu faible, ESP32 connecté en veille
  scanning()  — bleu rapide, scan WiFi
  capturing() — cyan moyen, capture EAPOL
  cracking()  — orange très rapide, hashcat en cours
  found()     — vert fixe, mot de passe trouvé !
  error()     — rouge lent, erreur
"""

from machine import Pin, Timer

# ── Timer logiciel (persiste entre les sessions mpremote) ──────────
_tim = Timer(-1)
_bv  = [False, 0, 0, 0]   # [phase, r, g, b]

# ── Détection matérielle ────────────────────────────────────────────
_np  = None    # NeoPixel si dispo
_led = None    # LED simple sinon

def _init():
    global _np, _led
    if _np is not None or _led is not None:
        return
    try:
        from neopixel import NeoPixel as _NP
        # Essai des pins NeoPixel courants : ESP32-C3=8, S3=48, S2=18
        for _pin in (8, 48, 18, 38, 10):
            try:
                candidate = _NP(Pin(_pin, Pin.OUT), 1)
                candidate[0] = (0, 0, 0)
                candidate.write()
                _np = candidate
                break
            except Exception:
                pass
    except Exception:
        pass
    if _np is None:
        # Fallback : LED bleue GPIO 2 (ESP32 DevKit, active HIGH)
        _led = Pin(2, Pin.OUT, value=0)

_init()

# ── Primitives ──────────────────────────────────────────────────────

def _color(r, g, b):
    if _np:
        _np[0] = (r, g, b)
        _np.write()
    elif _led:
        _led.value(1 if (r or g or b) else 0)

def _stop():
    _tim.deinit()

def _solid(r, g, b):
    _stop()
    _color(r, g, b)

def _blink(r, g, b, ms=300):
    _stop()
    _bv[0] = False
    _bv[1] = r; _bv[2] = g; _bv[3] = b
    def _cb(t):
        _bv[0] = not _bv[0]
        if _bv[0]:
            _color(_bv[1], _bv[2], _bv[3])
        else:
            _color(0, 0, 0)
    _tim.init(period=ms, mode=Timer.PERIODIC, callback=_cb)

# ── États publics ───────────────────────────────────────────────────

def off():
    _stop(); _color(0, 0, 0)

def idle():
    _solid(0, 0, 8)              # bleu très faible

def scanning():
    _blink(0, 0, 50, 120)        # bleu rapide

def capturing():
    _blink(0, 30, 30, 280)       # cyan moyen

def cracking():
    _blink(50, 15, 0, 80)        # orange très rapide (< 100ms)

def found():
    _solid(0, 60, 0)             # vert brillant fixe

def error():
    _blink(60, 0, 0, 500)        # rouge lent
