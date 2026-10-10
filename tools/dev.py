"""Developer command line for exploring the game and capturing templates.

    python tools/dev.py [--adb SERIAL] COMMAND ...

    shot [name]                         save a screenshot to logs/dev/<name>.png
    tap X Y [times]
    key K [times]
    swipe X1 Y1 X2 Y2 [ms]
    zoomout
    crop KEY X Y W H [threshold] [shot] save a template (from a saved shot or a fresh one)
    match KEY [shot]                    best score of a template
    ocr X Y W H [shot]                  read text in a region
    zoom X Y W H [shot] [scale]         enlarged crop -> logs/dev/zoom.png

After any command that clicks or types, the window that was in front before
(e.g. Claude or VS Code) is brought back to the front.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import win32gui  # noqa: E402

from bot import paths  # noqa: E402
from bot.core import vision  # noqa: E402
from bot.core.devices import AdbDevice, PcDevice  # noqa: E402
from bot.core.window import bring_to_front  # noqa: E402

DEV = os.path.join(paths.LOGS, "dev")
os.makedirs(DEV, exist_ok=True)


def load(name):
    p = os.path.join(DEV, name + ".png")
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def main(argv):
    if argv[:1] == ["--adb"]:
        dev, argv = AdbDevice(argv[1]), argv[2:]
    else:
        dev = PcDevice()
    cmd, args = (argv[0], argv[1:]) if argv else ("help", [])
    previous = win32gui.GetForegroundWindow()

    try:
        if cmd == "shot":
            name = args[0] if args else "shot"
            p = os.path.join(DEV, name + ".png")
            cv2.imencode(".png", dev.capture())[1].tofile(p)
            print(p)
        elif cmd == "tap":
            for i in range(int(args[2]) if len(args) > 2 else 1):
                dev.tap(int(args[0]), int(args[1]))
                time.sleep(0.1)
        elif cmd == "key":
            for _ in range(int(args[1]) if len(args) > 1 else 1):
                dev.key(args[0])
                time.sleep(0.05)
        elif cmd == "swipe":
            x1, y1, x2, y2 = map(int, args[:4])
            dev.swipe(x1, y1, x2, y2, int(args[4]) if len(args) > 4 else 500)
        elif cmd == "zoomout":
            dev.zoom_out()
        elif cmd == "variant":                       # variant KEY X Y W H [shot]: another look of KEY
            key, box = args[0], list(map(int, args[1:5]))
            frame = load(args[5]) if len(args) > 5 else dev.capture()
            vk = vision.templates.next_variant(key)
            x, y, w, h = box
            p = vision.templates.path(vk)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            cv2.imencode(".png", frame[y:y + h, x:x + w])[1].tofile(p)
            print("saved variant", p)
        elif cmd == "crop":
            key, box = args[0], list(map(int, args[1:5]))
            thr = float(args[5]) if len(args) > 5 else vision.DEFAULT_THRESHOLD
            frame = load(args[6]) if len(args) > 6 else dev.capture()
            vision.templates.save(key, frame, box, threshold=thr)
            print("saved", vision.templates.path(key), vision.templates.meta(key))
        elif cmd == "match":
            frame = load(args[1]) if len(args) > 1 else dev.capture()
            t = time.perf_counter()
            m = vision.find(frame, args[0], threshold=0, any_brightness=True)
            print(f"{args[0]}: score={m.score:.3f} at {m.center} box={m.box} "
                  f"({(time.perf_counter() - t) * 1000:.1f} ms)")
        elif cmd == "ocr":
            region = list(map(int, args[:4]))
            frame = load(args[4]) if len(args) > 4 else dev.capture()
            t = time.perf_counter()
            for text, conf, box in vision.text_reader.read(frame, region):
                print(f"{conf:.2f} {box} {text!r}")
            print(f"({(time.perf_counter() - t) * 1000:.0f} ms)")
        elif cmd == "zoom":
            x, y, w, h = map(int, args[:4])
            frame = load(args[4]) if len(args) > 4 else dev.capture()
            s = float(args[5]) if len(args) > 5 else 3
            crop = cv2.resize(frame[y:y + h, x:x + w], None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST)
            p = os.path.join(DEV, "zoom.png")
            cv2.imencode(".png", crop)[1].tofile(p)
            print(p)
        else:
            print(__doc__)
    finally:
        if cmd in ("tap", "key", "swipe", "zoomout") and isinstance(dev, PcDevice):
            time.sleep(0.3)
            bring_to_front(previous)


if __name__ == "__main__":
    main(sys.argv[1:])
