import ctypes
from ctypes import wintypes
from control import KEYS

ULONG_PTR = ctypes.c_size_t
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]
class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD), ('wParamH', wintypes.WORD)]
class UNION(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]
class INPUT(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('u', UNION)]
send_input = ctypes.windll.user32.SendInput
send_input.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
send_input.restype = wintypes.UINT

def emit(item):
    if send_input(1, ctypes.byref(item), ctypes.sizeof(INPUT)) != 1:
        raise OSError('Windows rejected input; run the game without administrator privileges')

def backend(kind, value, down):
    if kind == 'game-fullscreen':
        from window_mode import toggle_game_window
        toggle_game_window()
    elif kind == 'windowed':
        from window_mode import restore_all
        restore_all()
    elif kind == 'key':
        if value == 'f11' and down:
            from window_mode import restore_game_window
            if restore_game_window():return
        emit(INPUT(type=1, u=UNION(ki=KEYBDINPUT(wScan=KEYS[value], dwFlags=0x0008 | (0 if down else 0x0002)))))
    elif kind == 'text':
        raw = value.encode('utf-16-le')
        for i in range(0, len(raw), 2):
            unit = int.from_bytes(raw[i:i+2], 'little')
            for flags in (0x0004, 0x0004 | 0x0002):
                emit(INPUT(type=1, u=UNION(ki=KEYBDINPUT(wScan=unit, dwFlags=flags))))
    elif kind == 'pointer':
        # The captured primary monitor starts at (0, 0), even with monitors to its left.
        # Use physical pixels like MSS, including on Windows display scaling.
        awareness = ctypes.windll.user32.SetThreadDpiAwarenessContext
        awareness.argtypes = [ctypes.c_void_p]
        awareness.restype = ctypes.c_void_p
        previous = awareness(ctypes.c_void_p(-4))
        try:
            metrics = ctypes.windll.user32.GetSystemMetrics
            x, y = value[0] * (metrics(0)-1), value[1] * (metrics(1)-1)
            vx, vy, vw, vh = metrics(76), metrics(77), metrics(78), metrics(79)
        finally:
            if previous:
                awareness(previous)
        dx = round((x-vx)*65535/max(1,vw-1))
        dy = round((y-vy)*65535/max(1,vh-1))
        emit(INPUT(type=0, u=UNION(mi=MOUSEINPUT(dx=dx, dy=dy, dwFlags=0x0001|0x8000|0x4000))))
    elif kind == 'scroll':
        emit(INPUT(type=0, u=UNION(mi=MOUSEINPUT(mouseData=(value*120)&0xffffffff, dwFlags=0x0800))))
    elif kind == 'move':
        emit(INPUT(type=0, u=UNION(mi=MOUSEINPUT(dx=value[0], dy=value[1], dwFlags=0x0001|0x2000))))
    elif kind == 'button':
        flag = (0x0002 if down else 0x0004) if value == 'left' else (0x0008 if down else 0x0010)
        emit(INPUT(type=0, u=UNION(mi=MOUSEINPUT(dwFlags=flag))))
