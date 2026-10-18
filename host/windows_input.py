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
    if kind == 'key':
        emit(INPUT(type=1, u=UNION(ki=KEYBDINPUT(wScan=KEYS[value], dwFlags=0x0008 | (0 if down else 0x0002)))))
    elif kind == 'text':
        raw = value.encode('utf-16-le')
        for i in range(0, len(raw), 2):
            unit = int.from_bytes(raw[i:i+2], 'little')
            for flags in (0x0004, 0x0004 | 0x0002):
                emit(INPUT(type=1, u=UNION(ki=KEYBDINPUT(wScan=unit, dwFlags=flags))))
    elif kind == 'move':
        emit(INPUT(type=0, u=UNION(mi=MOUSEINPUT(dx=value[0], dy=value[1], dwFlags=0x0001))))
    elif kind == 'button':
        flag = (0x0002 if down else 0x0004) if value == 'left' else (0x0008 if down else 0x0010)
        emit(INPUT(type=0, u=UNION(mi=MOUSEINPUT(dwFlags=flag))))
