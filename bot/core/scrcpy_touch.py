"""Multi-touch over ADB using the scrcpy server (no root, any Android 5+).

`adb shell input` can only do one finger, so it cannot pinch to zoom. The scrcpy
server accepts injected touch events for several pointers at once. We start it
with a tiny 1-fps video stream (the server maps touch coordinates through the
video size) and discard the video.
"""

import os
import random
import socket
import struct
import subprocess
import threading
import time

REMOTE_JAR = "/data/local/tmp/scrcpy-server.jar"
ACTION_DOWN, ACTION_UP, ACTION_MOVE = 0, 1, 2
MSG_INJECT_TOUCH = 2


def _scrcpy_version(scrcpy_dir):
    exe = os.path.join(scrcpy_dir, "scrcpy.exe")
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10,
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout
    return out.split()[1]


class ScrcpyTouch:
    def __init__(self, adb, serial, scrcpy_dir):
        server = os.path.join(scrcpy_dir, "scrcpy-server")
        if not os.path.exists(server):
            raise RuntimeError(f"scrcpy-server not found in {scrcpy_dir}")
        self.adb, self.serial = adb, serial
        version = _scrcpy_version(scrcpy_dir)
        scid = "%08x" % random.randint(1, 0x7FFFFFFF)
        self.port = random.randint(27200, 27999)

        self._adb("push", server, REMOTE_JAR)
        self._adb("forward", f"tcp:{self.port}", f"localabstract:scrcpy_{scid}")
        self._proc = subprocess.Popen(
            [adb, "-s", serial, "shell", f"CLASSPATH={REMOTE_JAR}", "app_process", "/",
             "com.genymobile.scrcpy.Server", version, f"scid={scid}", "log_level=warn",
             "tunnel_forward=true", "audio=false", "control=true", "video=true",
             "max_fps=1", "video_bit_rate=500000", "send_device_meta=false", "cleanup=true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)

        self._video = self._connect_first()
        self._control = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        # Video socket starts with codec id + width + height (12 bytes).
        meta = self._recv_exact(self._video, 12)
        _, self.width, self.height = struct.unpack(">III", meta)
        threading.Thread(target=self._drain, daemon=True).start()

    def _adb(self, *args):
        subprocess.run([self.adb, "-s", self.serial, *args], capture_output=True, timeout=30,
                       creationflags=subprocess.CREATE_NO_WINDOW)

    def _connect_first(self):
        # adb accepts the TCP connection even before the server listens; the server's
        # "dummy byte" tells us it is really there.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
            try:
                if s.recv(1):
                    return s
            except OSError:
                pass
            s.close()
            time.sleep(0.3)
        raise RuntimeError("scrcpy server did not start")

    @staticmethod
    def _recv_exact(s, n):
        buf = b""
        while len(buf) < n:
            chunk = s.recv(n - len(buf))
            if not chunk:
                raise RuntimeError("scrcpy connection closed")
            buf += chunk
        return buf

    def _drain(self):
        try:
            while self._video.recv(65536):
                pass
        except OSError:
            pass

    def _touch(self, action, pointer_id, x, y, native_w, native_h):
        # Device coordinates -> video coordinates (they can differ if the video is downscaled).
        vx = round(x * self.width / native_w)
        vy = round(y * self.height / native_h)
        pressure = 0 if action == ACTION_UP else 0xFFFF
        msg = struct.pack(">BBqiiHHHii", MSG_INJECT_TOUCH, action, pointer_id, vx, vy,
                          self.width, self.height, pressure, 0, 0)
        self._control.sendall(msg)

    def pinch_in(self, cx, cy, start, end, steps=12, native=None):
        """Two fingers move from `start` px apart-from-centre to `end` (zoom out)."""
        nw, nh = native or (self.width, self.height)
        self._touch(ACTION_DOWN, 1, cx - start, cy, nw, nh)
        self._touch(ACTION_DOWN, 2, cx + start, cy, nw, nh)
        for i in range(1, steps + 1):
            d = start + (end - start) * i // steps
            self._touch(ACTION_MOVE, 1, cx - d, cy, nw, nh)
            self._touch(ACTION_MOVE, 2, cx + d, cy, nw, nh)
            time.sleep(0.015)
        self._touch(ACTION_UP, 1, cx - end, cy, nw, nh)
        self._touch(ACTION_UP, 2, cx + end, cy, nw, nh)

    def close(self):
        for s in (self._control, self._video):
            try:
                s.close()
            except OSError:
                pass
        if self._proc.poll() is None:
            self._proc.kill()
        self._adb("forward", "--remove", f"tcp:{self.port}")
