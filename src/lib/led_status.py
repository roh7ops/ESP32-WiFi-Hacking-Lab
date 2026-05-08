"""
LED status — ESP32 DevKit v1, GPIO 2 (LED bleue built-in)
Pas de NeoPixel : les états sont différenciés par le rythme de clignotement.

États :
  off()       → éteinte
  idle()      → double battement toutes les 3s  (ESP32 connecté, en veille)
  scanning()  → 150ms on/off régulier           (scan WiFi)
  capturing() → 350ms on/off régulier           (capture EAPOL)
  cracking()  → 80ms on/off très rapide         (hashcat en cours)
  found()     → 3 blinks rapides puis fixe      (mot de passe trouvé !)
  error()     → flash 100ms toutes les 900ms    (handshake échoué)
"""

from machine import Pin, Timer

# ── Configuration ─────────────────────────────────────────────────────
_LED_PIN = 2      # GPIO LED bleue built-in ESP32 DevKit v1
_LED_LOW = False  # True uniquement si ta LED est câblée active-LOW

# ── Init ──────────────────────────────────────────────────────────────
_tim = Timer(-1)
_led = Pin(_LED_PIN, Pin.OUT, value=int(_LED_LOW))

# ── Primitives ────────────────────────────────────────────────────────

def _on():
    _led.value(0 if _LED_LOW else 1)

def _off():
    _led.value(1 if _LED_LOW else 0)

def _stop():
    _tim.deinit()

def _blink(ms):
    """Clignotement symétrique à période fixe."""
    _stop()
    _s = [0]
    def _cb(t):
        _s[0] ^= 1
        (_on if _s[0] else _off)()
    _tim.init(period=ms, mode=Timer.PERIODIC, callback=_cb)

def _seq(steps, period_ms):
    """
    Séquence cyclique à partir d'une liste de 0/1.
    Chaque élément = 1 tick de period_ms ms.
    """
    _stop()
    _i = [0]
    def _cb(t):
        (_on if steps[_i[0]] else _off)()
        _i[0] = (_i[0] + 1) % len(steps)
    _tim.init(period=period_ms, mode=Timer.PERIODIC, callback=_cb)

# ── États publics ─────────────────────────────────────────────────────

def off():
    """LED éteinte."""
    _stop()
    _off()

def idle():
    """
    Double battement toutes les 3s — ESP32 en veille.
    ON-OFF-ON-OFF puis 2.6s de pause.
    """
    # 26 ticks × 100ms = 2.6s pause + 4 ticks = 3s total
    _seq([1,0,1,0] + [0]*26, 100)

def scanning():
    """Clignotement rapide régulier 150ms — scan WiFi."""
    _blink(150)

def capturing():
    """Clignotement moyen régulier 350ms — capture EAPOL."""
    _blink(350)

def cracking():
    """Clignotement très rapide 80ms — hashcat en cours."""
    _blink(80)

def found():
    """
    3 blinks rapides (150ms) puis LED fixe allumée.
    Annonce la découverte du mot de passe.
    """
    _stop()
    _n = [0]
    def _cb(t):
        _n[0] += 1
        if _n[0] <= 6:
            # 3 cycles on/off : ticks 1,3,5=on  2,4,6=off
            (_on if _n[0] % 2 == 1 else _off)()
        else:
            # reste allumée — stop le timer
            _on()
            _tim.deinit()
    _tim.init(period=150, mode=Timer.PERIODIC, callback=_cb)

def error():
    """
    Flash court (100ms) toutes les 900ms — erreur ou handshake échoué.
    1 tick ON + 9 ticks OFF × 100ms = 1 flash par seconde.
    """
    _seq([1] + [0]*9, 100)
