"""Validated input protocol; no arbitrary execution or key combinations."""
import math
import time

KEYS = {'w': 0x11, 'a': 0x1E, 's': 0x1F, 'd': 0x20, 'space': 0x39,
        'shift': 0x2A, 'ctrl': 0x1D, 'e': 0x12, 'escape': 0x01,
        'f11': 0x57, 't': 0x14, 'enter': 0x1C, 'backspace': 0x0E,
        **{str(n): n + 1 for n in range(1, 10)}}

class Controller:
    def __init__(self, backend):
        self.backend = backend
        self.held = set()
        self.last = time.monotonic()

    def release(self):
        for kind, key in list(self.held):
            self.backend(kind, key, False)
        self.held.clear()

    def handle(self, message):
        if not isinstance(message, dict):
            return
        kind = message.get('type')
        if kind == 'ping':
            self.last = time.monotonic()
        elif kind == 'release':
            self.release()
        elif kind in ('key', 'button'):
            key, down = message.get('key'), message.get('down')
            allowed = KEYS if kind == 'key' else ('left', 'right')
            if not isinstance(key, str) or key not in allowed or type(down) is not bool:
                return
            item = (kind, key)
            if down and item not in self.held:
                self.backend(kind, key, True)
                self.held.add(item)
            elif not down and item in self.held:
                self.backend(kind, key, False)
                self.held.remove(item)
        elif kind == 'move':
            x, y = message.get('x'), message.get('y')
            if all(type(v) in (int, float) and math.isfinite(v) for v in (x, y)):
                self.backend('move', (max(-300, min(300, int(x))), max(-300, min(300, int(y)))), False)
        elif kind == 'game-fullscreen':
            self.release()
            self.backend('game-fullscreen', None, False)
        elif kind == 'pointer':
            x, y = message.get('x'), message.get('y')
            if all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in (x, y)):
                self.backend('pointer', (x, y), False)
        elif kind == 'scroll':
            steps = message.get('steps')
            if type(steps) is int and -10 <= steps <= 10 and steps != 0:
                self.backend('scroll', steps, False)
        elif kind == 'text':
            value = message.get('text')
            if isinstance(value, str) and 0 < len(value) <= 200 and not any(ord(c) < 32 for c in value):
                self.backend('text', value, False)

    def watchdog(self):
        if time.monotonic() - self.last > 2:
            self.release()
