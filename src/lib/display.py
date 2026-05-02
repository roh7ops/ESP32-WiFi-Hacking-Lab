import utime

# Codes ANSI
_R = "\033[91m"   # rouge
_G = "\033[92m"   # vert
_Y = "\033[93m"   # jaune
_C = "\033[96m"   # cyan
_B = "\033[1m"    # gras
_X = "\033[0m"    # reset

_t0 = utime.ticks_ms()


def _ts():
    s = utime.ticks_diff(utime.ticks_ms(), _t0) // 1000
    return "[{:>5}s]".format(s)


def banner():
    print(_C + _B + """
  ╔══════════════════════════════════╗
  ║    ESP32  WiFi  Hacking  Lab     ║
  ║    MicroPython v1.25.0           ║
  ╚══════════════════════════════════╝""" + _X)


def info(msg):
    print("{} {}[*]{} {}".format(_ts(), _C, _X, msg))


def ok(msg):
    print("{} {}[+]{} {}".format(_ts(), _G, _X, msg))


def warn(msg):
    print("{} {}[!]{} {}".format(_ts(), _Y, _X, msg))


def err(msg):
    print("{} {}[x]{} {}".format(_ts(), _R, _X, msg))


def table(headers, rows, col=20):
    sep = "+" + ("-" * col + "+") * len(headers)
    fmt = "|" + ("{{:<{}}}|".format(col)) * len(headers)
    print(sep)
    print(fmt.format(*[str(h)[:col] for h in headers]))
    print(sep)
    for row in rows:
        print(fmt.format(*[str(v)[:col] for v in row]))
    print(sep)


def line(width=42):
    print("─" * width)


def menu(title, options):
    """Affiche un menu numéroté et retourne le choix saisi."""
    line()
    print("  " + _B + title + _X)
    line()
    for i, label in enumerate(options):
        print("  [{}] {}".format(i + 1, label))
    print("  [0] Quitter")
    line()
    try:
        return int(input("  Choix : "))
    except (ValueError, EOFError):
        return -1
