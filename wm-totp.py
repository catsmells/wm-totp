#!/usr/bin/env python3
import sys
import time
import math
import json
import hmac
import base64
import hashlib
import struct
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from Xlib import X, display as xdisplay, Xutil
SIZE = 64
FPS = 20
ACCOUNTS_FILE = Path.home() / '.config' / 'wm-totp' / 'accounts.json'
DEMO = {'name': 'DEMO', 'secret': 'JBSWY3DPEHPK3PXP', 'period': 30}
def _hotp(key: bytes, counter: int, digits: int = 6) -> str:
    msg = struct.pack('>Q', counter)
    h = hmac.new(key, msg, digestmod=hashlib.sha1).digest()
    off = h[-1] & 0x0F
    n = struct.unpack('>I', h[off:off+4])[0] & 0x7FFF_FFFF
    return f'{n % 10**digits:0{digits}d}'
def get_totp(secret: str, period: int = 30, digits: int = 6) -> tuple[str, float]:
    key = base64.b32decode(secret.upper().replace(' ', ''))
    now = time.time()
    counter = int(now) // period
    remaining = period - (now % period)
    return _hotp(key, counter, digits), remaining
_SEGS = {
    '0': 'abcdef',  '1': 'bc',     '2': 'abdeg',  '3': 'abcdg',
    '4': 'bcfg',    '5': 'acdfg',  '6': 'acdefg', '7': 'abc',
    '8': 'abcdefg', '9': 'abcdfg', '-': 'g',       ' ': '',
}
def _draw_digit(draw: ImageDraw.ImageDraw,
                ch: str, x: int, y: int,
                W: int, H: int, sw: int,
                on, off):
    segs = _SEGS.get(ch, '')
    H2 = H // 2
    coords = {
        'a': ((x+sw, y),       (x+W-sw, y)),
        'b': ((x+W,  y+sw),    (x+W,    y+H2-sw)),
        'c': ((x+W,  y+H2+sw), (x+W,    y+H-sw)),
        'd': ((x+sw, y+H),     (x+W-sw, y+H)),
        'e': ((x,    y+H2+sw), (x,      y+H-sw)),
        'f': ((x,    y+sw),    (x,      y+H2-sw)),
        'g': ((x+sw, y+H2),    (x+W-sw, y+H2)),
    }
    for seg, (p1, p2) in coords.items():
        draw.line([p1, p2], fill=on if seg in segs else off, width=sw)
def _time_color(frac: float) -> tuple[int, int, int]:
    if frac > 0.5:
        return (0, 210, 255)
    if frac > 0.2:
        t = (frac - 0.2) / 0.3
        return (int(255*(1-t)), int(180+75*t), int(255*t))
    t = frac / 0.2
    return (255, int(200*t), 0)
def render(code: str,
           remaining: float,
           period: float,
           pulse: float,
           flash: float,
           n_accounts: int,
           idx: int) -> Image.Image:
    img  = Image.new('RGBA', (SIZE, SIZE), (4, 4, 10, 255))
    draw = ImageDraw.Draw(img)
    frac = max(0.0, min(1.0, remaining / period))
    r, g, b = _time_color(frac)
    pr = int(r * pulse)
    pg = int(g * pulse)
    pb = int(b * pulse)
    if frac > 0.005:
        end_deg = -90 + 360 * frac
        glow = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.arc([2, 2, 61, 61], start=-90, end=end_deg,
               fill=(pr, pg, pb, 200), width=9)
        glow = glow.filter(ImageFilter.GaussianBlur(radius=3.5))
        img = Image.alpha_composite(img, glow)
        draw = ImageDraw.Draw(img)
        draw.arc([4, 4, 59, 59], start=-90, end=end_deg,
                 fill=(pr, pg, pb, 255), width=2)
    for y in range(0, SIZE, 4):
        draw.line([(0, y), (SIZE-1, y)], fill=(0, 0, 0, 18))
    if flash > 0:
        fl = int(flash * 55)
        overlay = Image.new('RGBA', (SIZE, SIZE), (fl, fl+5, fl+15, int(flash * 140)))
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)
    DW, DH, SW = 8, 14, 2
    GAP = 4
    total_w = 6 * DW + GAP
    dx = (SIZE - total_w) // 2
    dy = SIZE // 2 - DH // 2 + 1
    on_color = (pr, pg, pb)
    off_color = (max(0, pr//9), max(0, pg//9), max(0, pb//9))
    for i, ch in enumerate(code):
        x_off = GAP if i >= 3 else 0
        _draw_digit(draw, ch, dx + i*DW + x_off, dy, DW, DH, SW,
                    on_color, off_color)
    if n_accounts > 1:
        dots = min(n_accounts, 8)
        dot_w = 3
        dot_gap = 2
        row_w = dots * dot_w + (dots-1) * dot_gap
        sx = (SIZE - row_w) // 2
        for i in range(dots):
            col = (pr, pg, pb) if i == (idx % dots) else (25, 25, 38)
            x0 = sx + i * (dot_w + dot_gap)
            draw.rectangle([x0, 56, x0+dot_w-1, 58], fill=col)
    return img.convert('RGB')
def _to_xdata(img: Image.Image, depth: int) -> bytes:
    a = np.array(img.convert('RGB'), dtype=np.uint8)
    out = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    out[..., 0] = a[..., 2]
    out[..., 1] = a[..., 1]
    out[..., 2] = a[..., 0]
    if depth == 32:
        out[..., 3] = 255
    return out.tobytes()
class DockApp:
    def __init__(self):
        self.accounts   = self._load()
        self.idx        = 0
        self.flash      = 0.0
        self._last_code = None
        self.dpy    = xdisplay.Display()
        self.screen = self.dpy.screen()
        self._make_windows()
        self.gc = self.icon_win.create_gc()
    def _load(self) -> list:
        if ACCOUNTS_FILE.exists():
            try:
                data = json.loads(ACCOUNTS_FILE.read_text())
                return data if data else [DEMO]
            except Exception:
                pass
        return [DEMO]
    def _make_windows(self):
        s = self.screen
        root = s.root
        d = s.root_depth
        self.win = root.create_window(
            0, 0, SIZE, SIZE, 0, d, X.InputOutput, X.CopyFromParent,
            background_pixel=s.black_pixel,
            event_mask=X.ExposureMask | X.ButtonPressMask | X.StructureNotifyMask,
        )
        self.icon_win = self.win.create_window(
            0, 0, SIZE, SIZE, 0, d, X.InputOutput, X.CopyFromParent,
            background_pixel=s.black_pixel,
            event_mask=X.ExposureMask | X.ButtonPressMask,
        )
        self.win.set_wm_hints(
            flags=(Xutil.StateHint | Xutil.IconWindowHint | Xutil.WindowGroupHint),
            initial_state=Xutil.WithdrawnState,
            icon_window=self.icon_win,
            window_group=self.win,
        )
        self.win.set_wm_class('wm-totp', 'WMTotp')
        self.win.set_wm_name('wm-totp')
        self.win.map()
        self.icon_win.map()
        self.dpy.flush()
    def _blit(self, img: Image.Image):
        depth = self.screen.root_depth
        raw = _to_xdata(img, depth)
        self.icon_win.put_image(
            self.gc, 0, 0, SIZE, SIZE, X.ZPixmap, depth, 0, raw,
        )
        self.dpy.flush()
    def _tick(self):
        acc = self.accounts[self.idx]
        try:
            code, remaining = get_totp(acc['secret'], acc.get('period', 30))
        except Exception:
            code, remaining = '-----', 30.0
        if self._last_code is not None and code != self._last_code:
            self.flash = 1.0
        self._last_code = code
        if self.flash > 0:
            self.flash = max(0.0, self.flash - 0.08)
        period = acc.get('period', 30)
        if remaining < 8:
            pulse = 0.55 + 0.45 * (math.sin(time.time() * math.pi * 3) * 0.5 + 0.5)
        else:
            pulse = 1.0
        img = render(code, remaining, period, pulse, self.flash,
                     len(self.accounts), self.idx)
        self._blit(img)
    def _copy_code(self):
        acc = self.accounts[self.idx]
        try:
            code, _ = get_totp(acc['secret'], acc.get('period', 30))
            subprocess.run(['xclip', '-selection', 'clipboard'],
                           input=code.encode(), check=False)
        except Exception:
            pass
    def run(self):
        interval = 1.0 / FPS
        last = 0.0
        while True:
            while self.dpy.pending_events():
                ev = self.dpy.next_event()
                if ev.type == X.ButtonPress:
                    if ev.detail == 1:
                        self.idx = (self.idx + 1) % len(self.accounts)
                    elif ev.detail == 2:
                        self._copy_code()
                    elif ev.detail == 3:
                        self.accounts  = self._load()
                        self.idx = min(self.idx, len(self.accounts)-1)
                        self._last_code = None
                elif ev.type == X.DestroyNotify:
                    return
            now = time.time()
            if now - last >= interval:
                self._tick()
                last = now
            time.sleep(0.02)
if __name__ == '__main__':
    try:
        DockApp().run()
    except KeyboardInterrupt:
        pass
