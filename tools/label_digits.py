"""Create digit images from screenshots whose numbers you know.

    python tools/label_digits.py SHOT X Y W H TRUTH [SHOT X Y W H TRUTH ...]

Example (shot names are files in logs/dev without .png):
    python tools/label_digits.py home1 1600 28 230 44 2838649

Each digit found in the region is saved as digits/<digit>_<shot>_<n>.png, but only
if the number of digits found matches TRUTH (so nothing is mislabelled).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from bot import paths  # noqa: E402
from bot.core.profile import profile  # noqa: E402
from bot.core.vision import digits  # noqa: E402


def main(args):
    for i in range(0, len(args), 6):
        shot, x, y, w, h, truth = args[i:i + 6]
        p = os.path.join(paths.LOGS, "dev", shot + ".png")
        frame = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        glyphs = digits.glyphs(frame, (int(x), int(y), int(w), int(h)))
        boxes = [b for _, b in glyphs]
        if len(glyphs) != len(truth):
            print(f"{shot} {truth}: found {len(glyphs)} glyphs, expected {len(truth)} -> skipped {boxes}")
            continue
        for n, ((img, _), d) in enumerate(zip(glyphs, truth)):
            out = os.path.join(profile.digits, f"{d}_{shot}_{x}_{n}.png")
            cv2.imencode(".png", img)[1].tofile(out)
        print(f"{shot} {truth}: saved {len(truth)} digits, heights {[b[3] for b in boxes]}")
    digits.reload()


if __name__ == "__main__":
    main(sys.argv[1:])
