import atexit
import ctypes
import json
import os
import sys
import tkinter
from ctypes import wintypes

import win32api
import win32con

TYPE_SYNC = "SYNC"
TYPE_INFO = "INFO"
TYPE_READY = "READY"
TYPE_EVENT = "EVENT"
TYPE_ERROR = "ERROR"
EMPTY_CONTENT = {}


def send_message(mtype, content):
    message = {"type": mtype, "content": content}
    sys.stdout.write(json.dumps(message))
    sys.stdout.write(os.linesep)
    sys.stdout.flush()


def sync_notify():
    send_message(TYPE_SYNC, EMPTY_CONTENT)


def info_notify(dev, info):
    send_message(TYPE_INFO, {"device": dev, "info": info})


def ready_notify():
    send_message(TYPE_READY, EMPTY_CONTENT)


def event_notify(dev, event):
    send_message(TYPE_EVENT, {"device": dev, "event": event})


def error_notify(error, dev=None):
    send_message(TYPE_ERROR, {"device": dev, "message": error})


# input notifications
# https://docs.microsoft.com/en-us/windows/desktop/inputdev/keyboard-input-notifications
# https://docs.microsoft.com/en-us/windows/desktop/inputdev/mouse-input-notifications

WPARAM_TYPES = {
    0x0100: "WM_KEYDOWN",
    0x0101: "WM_KEYUP",
    0x0104: "WM_SYSKEYDOWN",
    0x0105: "WM_SYSKEYUP",
    0x0200: "WM_MOUSEMOVE",
    0x0201: "WM_LBUTTONDOWN",
    0x0202: "WM_LBUTTONUP",
    0x0204: "WM_RBUTTONDOWN",
    0x0205: "WM_RBUTTONUP",
    0x0207: "WM_MBUTTONDOWN",
    0x0208: "WM_MBUTTONUP",
    0x020A: "WM_MOUSEWHEEL",
    0x020B: "WM_XBUTTONDOWN",
    0x020C: "WM_XBUTTONUP",
    0x020E: "WM_MOUSEHWHEEL",
}

# virtual-key codes
# https://docs.microsoft.com/en-us/windows/desktop/inputdev/virtual-key-codes

VK_CODES = {
    0x01: "VK_LBUTTON",
    0x02: "VK_RBUTTON",
    0x03: "VK_CANCEL",
    0x04: "VK_MBUTTON",
    0x05: "VK_XBUTTON1",
    0x06: "VK_XBUTTON2",
    0x08: "VK_BACK",
    0x09: "VK_TAB",
    0x0C: "VK_CLEAR",
    0x0D: "VK_RETURN",
    0x10: "VK_SHIFT",
    0x11: "VK_CONTROL",
    0x12: "VK_MENU",
    0x13: "VK_PAUSE",
    0x14: "VK_CAPITAL",
    0x15: "VK_HANGUL",
    0x17: "VK_JUNJA",
    0x18: "VK_FINAL",
    0x19: "VK_KANJI",
    0x1B: "VK_ESCAPE",
    0x1C: "VK_CONVERT",
    0x1D: "VK_NONCONVERT",
    0x1E: "VK_ACCEPT",
    0x1F: "VK_MODECHANGE",
    0x20: "VK_SPACE",
    0x21: "VK_PRIOR",
    0x22: "VK_NEXT",
    0x23: "VK_END",
    0x24: "VK_HOME",
    0x25: "VK_LEFT",
    0x26: "VK_UP",
    0x27: "VK_RIGHT",
    0x28: "VK_DOWN",
    0x29: "VK_SELECT",
    0x2A: "VK_PRINT",
    0x2B: "VK_EXECUTE",
    0x2C: "VK_SNAPSHOT",
    0x2D: "VK_INSERT",
    0x2E: "VK_DELETE",
    0x2F: "VK_HELP",
    0x30: "VK_0",
    0x31: "VK_1",
    0x32: "VK_2",
    0x33: "VK_3",
    0x34: "VK_4",
    0x35: "VK_5",
    0x36: "VK_6",
    0x37: "VK_7",
    0x38: "VK_8",
    0x39: "VK_9",
    0x41: "VK_A",
    0x42: "VK_B",
    0x43: "VK_C",
    0x44: "VK_D",
    0x45: "VK_E",
    0x46: "VK_F",
    0x47: "VK_G",
    0x48: "VK_H",
    0x49: "VK_I",
    0x4A: "VK_J",
    0x4B: "VK_K",
    0x4C: "VK_L",
    0x4D: "VK_M",
    0x4E: "VK_N",
    0x4F: "VK_O",
    0x50: "VK_P",
    0x51: "VK_Q",
    0x52: "VK_R",
    0x53: "VK_S",
    0x54: "VK_T",
    0x55: "VK_U",
    0x56: "VK_V",
    0x57: "VK_W",
    0x58: "VK_X",
    0x59: "VK_Y",
    0x5A: "VK_Z",
    0x5B: "VK_LWIN",
    0x5C: "VK_RWIN",
    0x5D: "VK_APPS",
    0x5F: "VK_SLEEP",
    0x60: "VK_NUMPAD0",
    0x61: "VK_NUMPAD1",
    0x62: "VK_NUMPAD2",
    0x63: "VK_NUMPAD3",
    0x64: "VK_NUMPAD4",
    0x65: "VK_NUMPAD5",
    0x66: "VK_NUMPAD6",
    0x67: "VK_NUMPAD7",
    0x68: "VK_NUMPAD8",
    0x69: "VK_NUMPAD9",
    0x6A: "VK_MULTIPLY",
    0x6B: "VK_ADD",
    0x6C: "VK_SEPARATOR",
    0x6D: "VK_SUBTRACT",
    0x6E: "VK_DECIMAL",
    0x6F: "VK_DIVIDE",
    0x70: "VK_F1",
    0x71: "VK_F2",
    0x72: "VK_F3",
    0x73: "VK_F4",
    0x74: "VK_F5",
    0x75: "VK_F6",
    0x76: "VK_F7",
    0x77: "VK_F8",
    0x78: "VK_F9",
    0x79: "VK_F10",
    0x7A: "VK_F11",
    0x7B: "VK_F12",
    0x7C: "VK_F13",
    0x7D: "VK_F14",
    0x7E: "VK_F15",
    0x7F: "VK_F16",
    0x80: "VK_F17",
    0x81: "VK_F18",
    0x82: "VK_F19",
    0x83: "VK_F20",
    0x84: "VK_F21",
    0x85: "VK_F22",
    0x86: "VK_F23",
    0x87: "VK_F24",
    0x90: "VK_NUMLOCK",
    0x91: "VK_SCROLL",
    0x92: "VK_OEM_0x92",
    0x93: "VK_OEM_0x93",
    0x94: "VK_OEM_0x94",
    0x95: "VK_OEM_0x95",
    0x96: "VK_OEM_0x96",
    0xA0: "VK_LSHIFT",
    0xA1: "VK_RSHIFT",
    0xA2: "VK_LCONTROL",
    0xA3: "VK_RCONTROL",
    0xA4: "VK_LMENU",
    0xA5: "VK_RMENU",
    0xA6: "VK_BROWSER_BACK",
    0xA7: "VK_BROWSER_FORWARD",
    0xA8: "VK_BROWSER_REFRESH",
    0xA9: "VK_BROWSER_STOP",
    0xAA: "VK_BROWSER_SEARCH",
    0xAB: "VK_BROWSER_FAVORITES",
    0xAC: "VK_BROWSER_HOME",
    0xAD: "VK_VOLUME_MUTE",
    0xAE: "VK_VOLUME_DOWN",
    0xAF: "VK_VOLUME_UP",
    0xB0: "VK_MEDIA_NEXT_TRACK",
    0xB1: "VK_MEDIA_PREV_TRACK",
    0xB2: "VK_MEDIA_STOP",
    0xB3: "VK_MEDIA_PLAY_PAUSE",
    0xB4: "VK_LAUNCH_MAIL",
    0xB5: "VK_LAUNCH_MEDIA_SELECT",
    0xB6: "VK_LAUNCH_APP1",
    0xB7: "VK_LAUNCH_APP2",
    0xBA: "VK_OEM_1",
    0xBB: "VK_OEM_PLUS",
    0xBC: "VK_OEM_COMMA",
    0xBD: "VK_OEM_MINUS",
    0xBE: "VK_OEM_PERIOD",
    0xBF: "VK_OEM_2",
    0xC0: "VK_OEM_3",
    0xDB: "VK_OEM_4",
    0xDC: "VK_OEM_5",
    0xDD: "VK_OEM_6",
    0xDE: "VK_OEM_7",
    0xDF: "VK_OEM_8",
    0xE1: "VK_OEM_0xE1",
    0xE2: "VK_OEM_102",
    0xE3: "VK_OEM_0xE3",
    0xE4: "VK_OEM_0xE4",
    0xE5: "VK_PROCESSKEY",
    0xE6: "VK_OEM_0xE6",
    0xE7: "VK_PACKET",
    0xE9: "VK_OEM_0xE9",
    0xEA: "VK_OEM_0xEA",
    0xEB: "VK_OEM_0xEB",
    0xEC: "VK_OEM_0xEC",
    0xED: "VK_OEM_0xED",
    0xEE: "VK_OEM_0xEE",
    0xEF: "VK_OEM_0xEF",
    0xF0: "VK_OEM_0xF0",
    0xF1: "VK_OEM_0xF1",
    0xF2: "VK_OEM_0xF2",
    0xF3: "VK_OEM_0xF3",
    0xF4: "VK_OEM_0xF4",
    0xF5: "VK_OEM_0xF5",
    0xF6: "VK_ATTN",
    0xF7: "VK_CRSEL",
    0xF8: "VK_EXSEL",
    0xF9: "VK_EREOF",
    0xFA: "VK_PLAY",
    0xFB: "VK_ZOOM",
    0xFC: "VK_NONAME",
    0xFD: "VK_PA1",
    0xFE: "VK_OEM_CLEAR",
}


ULONG_PTR = wintypes.WPARAM
LRESULT = wintypes.LPARAM
HookProc = wintypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


# keyboard facilities

KEYBOARD_DEV = "keyboard"
KEYBOARD_HOOK = None


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = (
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


LPKBDLLHOOKSTRUCT = ctypes.POINTER(KBDLLHOOKSTRUCT)


@HookProc
def LowLevelKeyboardProc(nCode, wParam, lParam):
    global KEYBOARD_HOOK
    if nCode != win32con.HC_ACTION:
        return ctypes.windll.user32.CallNextHookEx(KEYBOARD_HOOK, nCode, wParam, lParam)

    raw_event = ctypes.cast(lParam, LPKBDLLHOOKSTRUCT)[0]
    flags = raw_event.flags
    flags_text = []
    if flags & 1:
        flags_text.append("EXTENDED")
    if (flags >> 5) & 1:
        flags_text.append("ALTDOWN")
    if (flags >> 7) & 1:
        flags_text.append("UP")
    event = {
        "typeNum": wParam,
        "typeName": WPARAM_TYPES.get(wParam, "UNKNOWN"),
        "vkCode": raw_event.vkCode,
        "vkCodeName": VK_CODES.get(raw_event.vkCode, "UNKNOWN"),
        "scanCode": raw_event.scanCode,
        "flags": flags,
        "flagsText": flags_text,
        "timestamp": raw_event.time,
    }
    event_notify(KEYBOARD_DEV, event)

    if raw_event.vkCode == win32con.VK_F11:
        return ctypes.windll.user32.CallNextHookEx(KEYBOARD_HOOK, nCode, wParam, lParam)
    else:
        return 1


def register_keyboard_hook():
    global KEYBOARD_HOOK
    handle = win32api.GetModuleHandle(None)
    KEYBOARD_HOOK = ctypes.windll.user32.SetWindowsHookExA(
        win32con.WH_KEYBOARD_LL, LowLevelKeyboardProc, handle, 0
    )
    atexit.register(ctypes.windll.user32.UnhookWindowsHookEx, KEYBOARD_HOOK)


def disable_hotkeys():
    # TODO: implement the function according to the following doc
    # https://docs.microsoft.com/en-us/windows/desktop/dxtecharts/disabling-shortcut-keys-in-games
    pass


# pointer facilities

MOUSE_DEV = "pointer"
MOUSE_HOOK = None


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = (
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    )


LPMSLLHOOKSTRUCT = ctypes.POINTER(MSLLHOOKSTRUCT)


@HookProc
def LowLevelMouseProc(nCode, wParam, lParam):
    global MOUSE_HOOK
    if nCode != win32con.HC_ACTION:
        return ctypes.windll.user32.CallNextHookEx(MOUSE_HOOK, nCode, wParam, lParam)

    raw_event = ctypes.cast(lParam, LPMSLLHOOKSTRUCT)[0]
    mouse_data = raw_event.mouseData
    mouse_data_text = ""
    if wParam in (0x020A, 0x020E):  # WM_MOUSEWHEEL and WM_MOUSEHWHEEL
        value = mouse_data >> 16
        if value == 0x0078:  # delta value is 120
            mouse_data_text = "WHEELFORWARD"
        elif value == 0xFF88:  # delta value is -120
            mouse_data_text = "WHEELBACKWARD"
    elif wParam in (0x020B, 0x020C):  # WM_XBUTTONDOWN and WM_XBUTTONUP
        value = mouse_data >> 16
        if value & 0x0001:
            mouse_data_text = "XBUTTON1"
        elif value & 0x0002:
            mouse_data_text = "XBUTTON2"
    event = {
        "typeNum": wParam,
        "typeName": WPARAM_TYPES.get(wParam, "UNKNOWN"),
        "xPos": raw_event.pt.x,
        "yPos": raw_event.pt.y,
        "mouseData": mouse_data,
        "mouseDataText": mouse_data_text,
        "flags": raw_event.flags,
        "timestamp": raw_event.time,
    }
    event_notify(MOUSE_DEV, event)

    return ctypes.windll.user32.CallNextHookEx(MOUSE_HOOK, nCode, wParam, lParam)


def register_pointer_hook():
    global MOUSE_HOOK
    handle = win32api.GetModuleHandle(None)
    MOUSE_HOOK = ctypes.windll.user32.SetWindowsHookExA(
        win32con.WH_MOUSE_LL, LowLevelMouseProc, handle, 0
    )
    atexit.register(ctypes.windll.user32.UnhookWindowsHookEx, MOUSE_HOOK)


class DesktopCover(object):
    def __init__(self):
        self.notified = False

        self.tk = tkinter.Tk()
        self.tk.attributes("-fullscreen", True)
        self.tk.attributes("-topmost", True)
        self.tk.focus()
        self.tk.grab_set_global()
        self.tk.bind("<Configure>", self.on_fullscreen)

        self.frame = tkinter.Frame(self.tk)
        self.frame.pack()

        self.label = tkinter.Label(self.frame, text="listening input events")
        self.label.grid()

    def on_fullscreen(self, event=None):
        if not self.notified:
            ready_notify()
            self.notified = True

    def mainloop(self):
        self.tk.mainloop()


if __name__ == "__main__":
    sync_notify()
    disable_hotkeys()

    register_keyboard_hook()
    info_notify(KEYBOARD_DEV, EMPTY_CONTENT)
    register_pointer_hook()
    info_notify(MOUSE_DEV, EMPTY_CONTENT)

    app = DesktopCover()
    app.mainloop()
