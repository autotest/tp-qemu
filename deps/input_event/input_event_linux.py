import json
import os
import select
import struct
import sys
import threading

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


EV_PACK_FMT = "llHHI"
EV_PACK_SIZE = struct.calcsize(EV_PACK_FMT)

EV_TYPES = {
    0x00: "EV_SYN",
    0x01: "EV_KEY",
    0x02: "EV_REL",
    0x03: "EV_ABS",
    0x04: "EV_MSC",
    0x05: "EV_SW",
    0x11: "EV_LED",
    0x12: "EV_SND",
    0x14: "EV_REP",
    0x15: "EV_FF",
    0x16: "EV_PWR",
    0x17: "EV_FF_STATUS",
}

EV_SYN_CODES = {0: "SYN_REPORT", 1: "SYN_CONFIG", 2: "SYN_MT_REPORT", 3: "SYN_DROPPED"}

EV_KEY_CODES = {
    0: "KEY_RESERVED",
    1: "KEY_ESC",
    2: "KEY_1",
    3: "KEY_2",
    4: "KEY_3",
    5: "KEY_4",
    6: "KEY_5",
    7: "KEY_6",
    8: "KEY_7",
    9: "KEY_8",
    10: "KEY_9",
    11: "KEY_0",
    12: "KEY_MINUS",
    13: "KEY_EQUAL",
    14: "KEY_BACKSPACE",
    15: "KEY_TAB",
    16: "KEY_Q",
    17: "KEY_W",
    18: "KEY_E",
    19: "KEY_R",
    20: "KEY_T",
    21: "KEY_Y",
    22: "KEY_U",
    23: "KEY_I",
    24: "KEY_O",
    25: "KEY_P",
    26: "KEY_LEFTBRACE",
    27: "KEY_RIGHTBRACE",
    28: "KEY_ENTER",
    29: "KEY_LEFTCTRL",
    30: "KEY_A",
    31: "KEY_S",
    32: "KEY_D",
    33: "KEY_F",
    34: "KEY_G",
    35: "KEY_H",
    36: "KEY_J",
    37: "KEY_K",
    38: "KEY_L",
    39: "KEY_SEMICOLON",
    40: "KEY_APOSTROPHE",
    41: "KEY_GRAVE",
    42: "KEY_LEFTSHIFT",
    43: "KEY_BACKSLASH",
    44: "KEY_Z",
    45: "KEY_X",
    46: "KEY_C",
    47: "KEY_V",
    48: "KEY_B",
    49: "KEY_N",
    50: "KEY_M",
    51: "KEY_COMMA",
    52: "KEY_DOT",
    53: "KEY_SLASH",
    54: "KEY_RIGHTSHIFT",
    55: "KEY_KPASTERISK",
    56: "KEY_LEFTALT",
    57: "KEY_SPACE",
    58: "KEY_CAPSLOCK",
    59: "KEY_F1",
    60: "KEY_F2",
    61: "KEY_F3",
    62: "KEY_F4",
    63: "KEY_F5",
    64: "KEY_F6",
    65: "KEY_F7",
    66: "KEY_F8",
    67: "KEY_F9",
    68: "KEY_F10",
    69: "KEY_NUMLOCK",
    70: "KEY_SCROLLLOCK",
    71: "KEY_KP7",
    72: "KEY_KP8",
    73: "KEY_KP9",
    74: "KEY_KPMINUS",
    75: "KEY_KP4",
    76: "KEY_KP5",
    77: "KEY_KP6",
    78: "KEY_KPPLUS",
    79: "KEY_KP1",
    80: "KEY_KP2",
    81: "KEY_KP3",
    82: "KEY_KP0",
    83: "KEY_KPDOT",
    85: "KEY_ZENKAKUHANKAKU",
    86: "KEY_102ND",
    87: "KEY_F11",
    88: "KEY_F12",
    89: "KEY_RO",
    90: "KEY_KATAKANA",
    91: "KEY_HIRAGANA",
    92: "KEY_HENKAN",
    93: "KEY_KATAKANAHIRAGANA",
    94: "KEY_MUHENKAN",
    95: "KEY_KPJPCOMMA",
    96: "KEY_KPENTER",
    97: "KEY_RIGHTCTRL",
    98: "KEY_KPSLASH",
    99: "KEY_SYSRQ",
    100: "KEY_RIGHTALT",
    101: "KEY_LINEFEED",
    102: "KEY_HOME",
    103: "KEY_UP",
    104: "KEY_PAGEUP",
    105: "KEY_LEFT",
    106: "KEY_RIGHT",
    107: "KEY_END",
    108: "KEY_DOWN",
    109: "KEY_PAGEDOWN",
    110: "KEY_INSERT",
    111: "KEY_DELETE",
    112: "KEY_MACRO",
    113: "KEY_MUTE",
    114: "KEY_VOLUMEDOWN",
    115: "KEY_VOLUMEUP",
    116: "KEY_POWER",
    117: "KEY_KPEQUAL",
    118: "KEY_KPPLUSMINUS",
    119: "KEY_PAUSE",
    120: "KEY_SCALE",
    121: "KEY_KPCOMMA",
    122: "KEY_HANGEUL",
    123: "KEY_HANJA",
    124: "KEY_YEN",
    125: "KEY_LEFTMETA",
    126: "KEY_RIGHTMETA",
    127: "KEY_COMPOSE",
    128: "KEY_STOP",
    129: "KEY_AGAIN",
    130: "KEY_PROPS",
    131: "KEY_UNDO",
    132: "KEY_FRONT",
    133: "KEY_COPY",
    134: "KEY_OPEN",
    135: "KEY_PASTE",
    136: "KEY_FIND",
    137: "KEY_CUT",
    138: "KEY_HELP",
    139: "KEY_MENU",
    140: "KEY_CALC",
    141: "KEY_SETUP",
    142: "KEY_SLEEP",
    143: "KEY_WAKEUP",
    144: "KEY_FILE",
    145: "KEY_SENDFILE",
    146: "KEY_DELETEFILE",
    147: "KEY_XFER",
    148: "KEY_PROG1",
    149: "KEY_PROG2",
    150: "KEY_WWW",
    151: "KEY_MSDOS",
    152: "KEY_SCREENLOCK",  # alias: KEY_COFFEE
    153: "KEY_DIRECTION",
    154: "KEY_CYCLEWINDOWS",
    155: "KEY_MAIL",
    156: "KEY_BOOKMARKS",
    157: "KEY_COMPUTER",
    158: "KEY_BACK",
    159: "KEY_FORWARD",
    160: "KEY_CLOSECD",
    161: "KEY_EJECTCD",
    162: "KEY_EJECTCLOSECD",
    163: "KEY_NEXTSONG",
    164: "KEY_PLAYPAUSE",
    165: "KEY_PREVIOUSSONG",
    166: "KEY_STOPCD",
    167: "KEY_RECORD",
    168: "KEY_REWIND",
    169: "KEY_PHONE",
    170: "KEY_ISO",
    171: "KEY_CONFIG",
    172: "KEY_HOMEPAGE",
    173: "KEY_REFRESH",
    174: "KEY_EXIT",
    175: "KEY_MOVE",
    176: "KEY_EDIT",
    177: "KEY_SCROLLUP",
    178: "KEY_SCROLLDOWN",
    179: "KEY_KPLEFTPAREN",
    180: "KEY_KPRIGHTPAREN",
    181: "KEY_NEW",
    182: "KEY_REDO",
    183: "KEY_F13",
    184: "KEY_F14",
    185: "KEY_F15",
    186: "KEY_F16",
    187: "KEY_F17",
    188: "KEY_F18",
    189: "KEY_F19",
    190: "KEY_F20",
    191: "KEY_F21",
    192: "KEY_F22",
    193: "KEY_F23",
    194: "KEY_F24",
    200: "KEY_PLAYCD",
    201: "KEY_PAUSECD",
    202: "KEY_PROG3",
    203: "KEY_PROG4",
    204: "KEY_DASHBOARD",
    205: "KEY_SUSPEND",
    206: "KEY_CLOSE",
    207: "KEY_PLAY",
    208: "KEY_FASTFORWARD",
    209: "KEY_BASSBOOST",
    210: "KEY_PRINT",
    211: "KEY_HP",
    212: "KEY_CAMERA",
    213: "KEY_SOUND",
    214: "KEY_QUESTION",
    215: "KEY_EMAIL",
    216: "KEY_CHAT",
    217: "KEY_SEARCH",
    218: "KEY_CONNECT",
    219: "KEY_FINANCE",
    220: "KEY_SPORT",
    221: "KEY_SHOP",
    222: "KEY_ALTERASE",
    223: "KEY_CANCEL",
    224: "KEY_BRIGHTNESSDOWN",
    225: "KEY_BRIGHTNESSUP",
    226: "KEY_MEDIA",
    227: "KEY_SWITCHVIDEOMODE",
    228: "KEY_KBDILLUMTOGGLE",
    229: "KEY_KBDILLUMDOWN",
    230: "KEY_KBDILLUMUP",
    231: "KEY_SEND",
    232: "KEY_REPLY",
    233: "KEY_FORWARDMAIL",
    234: "KEY_SAVE",
    235: "KEY_DOCUMENTS",
    236: "KEY_BATTERY",
    237: "KEY_BLUETOOTH",
    238: "KEY_WLAN",
    239: "KEY_UWB",
    240: "KEY_UNKNOWN",
    241: "KEY_VIDEO_NEXT",
    242: "KEY_VIDEO_PREV",
    243: "KEY_BRIGHTNESS_CYCLE",
    244: "KEY_BRIGHTNESS_ZERO",
    245: "KEY_DISPLAY_OFF",
    246: "KEY_WIMAX",
    247: "KEY_RFKILL",
    248: "KEY_MICMUTE",
    0x100: "BTN_0",  # alias: BTN_MISC
    0x101: "BTN_1",
    0x102: "BTN_2",
    0x103: "BTN_3",
    0x104: "BTN_4",
    0x105: "BTN_5",
    0x106: "BTN_6",
    0x107: "BTN_7",
    0x108: "BTN_8",
    0x109: "BTN_9",
    0x110: "BTN_LEFT",  # alias: BTN_MOUSE
    0x111: "BTN_RIGHT",
    0x112: "BTN_MIDDLE",
    0x113: "BTN_SIDE",
    0x114: "BTN_EXTRA",
    0x115: "BTN_FORWARD",
    0x116: "BTN_BACK",
    0x117: "BTN_TASK",
    0x120: "BTN_TRIGGER",  # alias: BTN_JOYSTICK
    0x121: "BTN_THUMB",
    0x122: "BTN_THUMB2",
    0x123: "BTN_TOP",
    0x124: "BTN_TOP2",
    0x125: "BTN_PINKIE",
    0x126: "BTN_BASE",
    0x127: "BTN_BASE2",
    0x128: "BTN_BASE3",
    0x129: "BTN_BASE4",
    0x12A: "BTN_BASE5",
    0x12B: "BTN_BASE6",
    0x12F: "BTN_DEAD",
    0x130: "BTN_A",  # alias: BTN_GAMEPAD
    0x131: "BTN_B",
    0x132: "BTN_C",
    0x133: "BTN_X",
    0x134: "BTN_Y",
    0x135: "BTN_Z",
    0x136: "BTN_TL",
    0x137: "BTN_TR",
    0x138: "BTN_TL2",
    0x139: "BTN_TR2",
    0x13A: "BTN_SELECT",
    0x13B: "BTN_START",
    0x13C: "BTN_MODE",
    0x13D: "BTN_THUMBL",
    0x13E: "BTN_THUMBR",
    0x140: "BTN_TOOL_PEN",  # alias: BTN_DIGI
    0x141: "BTN_TOOL_RUBBER",
    0x142: "BTN_TOOL_BRUSH",
    0x143: "BTN_TOOL_PENCIL",
    0x144: "BTN_TOOL_AIRBRUSH",
    0x145: "BTN_TOOL_FINGER",
    0x146: "BTN_TOOL_MOUSE",
    0x147: "BTN_TOOL_LENS",
    0x148: "BTN_TOOL_QUINTTAP",
    0x149: "BTN_STYLUS3",
    0x14A: "BTN_TOUCH",
    0x14B: "BTN_STYLUS",
    0x14C: "BTN_STYLUS2",
    0x14D: "BTN_TOOL_DOUBLETAP",
    0x14E: "BTN_TOOL_TRIPLETAP",
    0x14F: "BTN_TOOL_QUADTAP",
    0x150: "BTN_GEAR_DOWN",  # alias: BTN_WHEEL
    0x151: "BTN_GEAR_UP",
    0x160: "KEY_OK",
    0x161: "KEY_SELECT",
    0x162: "KEY_GOTO",
    0x163: "KEY_CLEAR",
    0x164: "KEY_POWER2",
    0x165: "KEY_OPTION",
    0x166: "KEY_INFO",
    0x167: "KEY_TIME",
    0x168: "KEY_VENDOR",
    0x169: "KEY_ARCHIVE",
    0x16A: "KEY_PROGRAM",
    0x16B: "KEY_CHANNEL",
    0x16C: "KEY_FAVORITES",
    0x16D: "KEY_EPG",
    0x16E: "KEY_PVR",
    0x16F: "KEY_MHP",
    0x170: "KEY_LANGUAGE",
    0x171: "KEY_TITLE",
    0x172: "KEY_SUBTITLE",
    0x173: "KEY_ANGLE",
    0x174: "KEY_ZOOM",
    0x175: "KEY_MODE",
    0x176: "KEY_KEYBOARD",
    0x177: "KEY_SCREEN",
    0x178: "KEY_PC",
    0x179: "KEY_TV",
    0x17A: "KEY_TV2",
    0x17B: "KEY_VCR",
    0x17C: "KEY_VCR2",
    0x17D: "KEY_SAT",
    0x17E: "KEY_SAT2",
    0x17F: "KEY_CD",
    0x180: "KEY_TAPE",
    0x181: "KEY_RADIO",
    0x182: "KEY_TUNER",
    0x183: "KEY_PLAYER",
    0x184: "KEY_TEXT",
    0x185: "KEY_DVD",
    0x186: "KEY_AUX",
    0x187: "KEY_MP3",
    0x188: "KEY_AUDIO",
    0x189: "KEY_VIDEO",
    0x18A: "KEY_DIRECTORY",
    0x18B: "KEY_LIST",
    0x18C: "KEY_MEMO",
    0x18D: "KEY_CALENDAR",
    0x18E: "KEY_RED",
    0x18F: "KEY_GREEN",
    0x190: "KEY_YELLOW",
    0x191: "KEY_BLUE",
    0x192: "KEY_CHANNELUP",
    0x193: "KEY_CHANNELDOWN",
    0x194: "KEY_FIRST",
    0x195: "KEY_LAST",
    0x196: "KEY_AB",
    0x197: "KEY_NEXT",
    0x198: "KEY_RESTART",
    0x199: "KEY_SLOW",
    0x19A: "KEY_SHUFFLE",
    0x19B: "KEY_BREAK",
    0x19C: "KEY_PREVIOUS",
    0x19D: "KEY_DIGITS",
    0x19E: "KEY_TEEN",
    0x19F: "KEY_TWEN",
    0x1A0: "KEY_VIDEOPHONE",
    0x1A1: "KEY_GAMES",
    0x1A2: "KEY_ZOOMIN",
    0x1A3: "KEY_ZOOMOUT",
    0x1A4: "KEY_ZOOMRESET",
    0x1A5: "KEY_WORDPROCESSOR",
    0x1A6: "KEY_EDITOR",
    0x1A7: "KEY_SPREADSHEET",
    0x1A8: "KEY_GRAPHICSEDITOR",
    0x1A9: "KEY_PRESENTATION",
    0x1AA: "KEY_DATABASE",
    0x1AB: "KEY_NEWS",
    0x1AC: "KEY_VOICEMAIL",
    0x1AD: "KEY_ADDRESSBOOK",
    0x1AE: "KEY_MESSENGER",
    0x1AF: "KEY_DISPLAYTOGGLE",
    0x1B0: "KEY_SPELLCHECK",
    0x1B1: "KEY_LOGOFF",
    0x1B2: "KEY_DOLLAR",
    0x1B3: "KEY_EURO",
    0x1B4: "KEY_FRAMEBACK",
    0x1B5: "KEY_FRAMEFORWARD",
    0x1B6: "KEY_CONTEXT_MENU",
    0x1B7: "KEY_MEDIA_REPEAT",
    0x1B8: "KEY_10CHANNELSUP",
    0x1B9: "KEY_10CHANNELSDOWN",
    0x1BA: "KEY_IMAGES",
    0x1C0: "KEY_DEL_EOL",
    0x1C1: "KEY_DEL_EOS",
    0x1C2: "KEY_INS_LINE",
    0x1C3: "KEY_DEL_LINE",
    0x1D0: "KEY_FN",
    0x1D1: "KEY_FN_ESC",
    0x1D2: "KEY_FN_F1",
    0x1D3: "KEY_FN_F2",
    0x1D4: "KEY_FN_F3",
    0x1D5: "KEY_FN_F4",
    0x1D6: "KEY_FN_F5",
    0x1D7: "KEY_FN_F6",
    0x1D8: "KEY_FN_F7",
    0x1D9: "KEY_FN_F8",
    0x1DA: "KEY_FN_F9",
    0x1DB: "KEY_FN_F10",
    0x1DC: "KEY_FN_F11",
    0x1DD: "KEY_FN_F12",
    0x1DE: "KEY_FN_1",
    0x1DF: "KEY_FN_2",
    0x1E0: "KEY_FN_D",
    0x1E1: "KEY_FN_E",
    0x1E2: "KEY_FN_F",
    0x1E3: "KEY_FN_S",
    0x1E4: "KEY_FN_B",
    0x1F1: "KEY_BRL_DOT1",
    0x1F2: "KEY_BRL_DOT2",
    0x1F3: "KEY_BRL_DOT3",
    0x1F4: "KEY_BRL_DOT4",
    0x1F5: "KEY_BRL_DOT5",
    0x1F6: "KEY_BRL_DOT6",
    0x1F7: "KEY_BRL_DOT7",
    0x1F8: "KEY_BRL_DOT8",
    0x1F9: "KEY_BRL_DOT9",
    0x1FA: "KEY_BRL_DOT10",
    0x200: "KEY_NUMERIC_0",
    0x201: "KEY_NUMERIC_1",
    0x202: "KEY_NUMERIC_2",
    0x203: "KEY_NUMERIC_3",
    0x204: "KEY_NUMERIC_4",
    0x205: "KEY_NUMERIC_5",
    0x206: "KEY_NUMERIC_6",
    0x207: "KEY_NUMERIC_7",
    0x208: "KEY_NUMERIC_8",
    0x209: "KEY_NUMERIC_9",
    0x20A: "KEY_NUMERIC_STAR",
    0x20B: "KEY_NUMERIC_POUND",
    0x210: "KEY_CAMERA_FOCUS",
    0x211: "KEY_WPS_BUTTON",
    0x212: "KEY_TOUCHPAD_TOGGLE",
    0x213: "KEY_TOUCHPAD_ON",
    0x214: "KEY_TOUCHPAD_OFF",
    0x215: "KEY_CAMERA_ZOOMIN",
    0x216: "KEY_CAMERA_ZOOMOUT",
    0x217: "KEY_CAMERA_UP",
    0x218: "KEY_CAMERA_DOWN",
    0x219: "KEY_CAMERA_LEFT",
    0x21A: "KEY_CAMERA_RIGHT",
    0x21B: "KEY_ATTENDANT_ON",
    0x21C: "KEY_ATTENDANT_OFF",
    0x21D: "KEY_ATTENDANT_TOGGLE",
    0x21E: "KEY_LIGHTS_TOGGLE",
    0x231: "KEY_ROTATE_LOCK_TOGGLE",
    0x240: "KEY_BUTTONCONFIG",
    0x243: "KEY_CONTROLPANEL",
    0x246: "KEY_VOICECOMMAND",
    0x250: "KEY_BRIGHTNESS_MIN",
    0x278: "KEY_ONSCREEN_KEYBOARD",
    0x2C0: "BTN_TRIGGER_HAPPY1",  # alias: BTN_TRIGGER_HAPPY
    0x2C1: "BTN_TRIGGER_HAPPY2",
    0x2C2: "BTN_TRIGGER_HAPPY3",
    0x2C3: "BTN_TRIGGER_HAPPY4",
    0x2C4: "BTN_TRIGGER_HAPPY5",
    0x2C5: "BTN_TRIGGER_HAPPY6",
    0x2C6: "BTN_TRIGGER_HAPPY7",
    0x2C7: "BTN_TRIGGER_HAPPY8",
    0x2C8: "BTN_TRIGGER_HAPPY9",
    0x2C9: "BTN_TRIGGER_HAPPY10",
    0x2CA: "BTN_TRIGGER_HAPPY11",
    0x2CB: "BTN_TRIGGER_HAPPY12",
    0x2CC: "BTN_TRIGGER_HAPPY13",
    0x2CD: "BTN_TRIGGER_HAPPY14",
    0x2CE: "BTN_TRIGGER_HAPPY15",
    0x2CF: "BTN_TRIGGER_HAPPY16",
    0x2D0: "BTN_TRIGGER_HAPPY17",
    0x2D1: "BTN_TRIGGER_HAPPY18",
    0x2D2: "BTN_TRIGGER_HAPPY19",
    0x2D3: "BTN_TRIGGER_HAPPY20",
    0x2D4: "BTN_TRIGGER_HAPPY21",
    0x2D5: "BTN_TRIGGER_HAPPY22",
    0x2D6: "BTN_TRIGGER_HAPPY23",
    0x2D7: "BTN_TRIGGER_HAPPY24",
    0x2D8: "BTN_TRIGGER_HAPPY25",
    0x2D9: "BTN_TRIGGER_HAPPY26",
    0x2DA: "BTN_TRIGGER_HAPPY27",
    0x2DB: "BTN_TRIGGER_HAPPY28",
    0x2DC: "BTN_TRIGGER_HAPPY29",
    0x2DD: "BTN_TRIGGER_HAPPY30",
    0x2DE: "BTN_TRIGGER_HAPPY31",
    0x2DF: "BTN_TRIGGER_HAPPY32",
    0x2E0: "BTN_TRIGGER_HAPPY33",
    0x2E1: "BTN_TRIGGER_HAPPY34",
    0x2E2: "BTN_TRIGGER_HAPPY35",
    0x2E3: "BTN_TRIGGER_HAPPY36",
    0x2E4: "BTN_TRIGGER_HAPPY37",
    0x2E5: "BTN_TRIGGER_HAPPY38",
    0x2E6: "BTN_TRIGGER_HAPPY39",
    0x2E7: "BTN_TRIGGER_HAPPY40",
}

EV_REL_CODES = {
    0x00: "REL_X",
    0x01: "REL_Y",
    0x02: "REL_Z",
    0x03: "REL_RX",
    0x04: "REL_RY",
    0x05: "REL_RZ",
    0x06: "REL_HWHEEL",
    0x07: "REL_DIAL",
    0x08: "REL_WHEEL",
    0x09: "REL_MISC",
}

EV_ABS_CODES = {
    0x00: "ABS_X",
    0x01: "ABS_Y",
    0x02: "ABS_Z",
    0x03: "ABS_RX",
    0x04: "ABS_RY",
    0x05: "ABS_RZ",
    0x06: "ABS_THROTTLE",
    0x07: "ABS_RUDDER",
    0x08: "ABS_WHEEL",
    0x09: "ABS_GAS",
    0x0A: "ABS_BRAKE",
    0x10: "ABS_HAT0X",
    0x11: "ABS_HAT0Y",
    0x12: "ABS_HAT1X",
    0x13: "ABS_HAT1Y",
    0x14: "ABS_HAT2X",
    0x15: "ABS_HAT2Y",
    0x16: "ABS_HAT3X",
    0x17: "ABS_HAT3Y",
    0x18: "ABS_PRESSURE",
    0x19: "ABS_DISTANCE",
    0x1A: "ABS_TILT_X",
    0x1B: "ABS_TILT_Y",
    0x1C: "ABS_TOOL_WIDTH",
    0x20: "ABS_VOLUME",
    0x28: "ABS_MISC",
    0x2F: "ABS_MT_SLOT",
    0x30: "ABS_MT_TOUCH_MAJOR",
    0x31: "ABS_MT_TOUCH_MINOR",
    0x32: "ABS_MT_WIDTH_MAJOR",
    0x33: "ABS_MT_WIDTH_MINOR",
    0x34: "ABS_MT_ORIENTATION",
    0x35: "ABS_MT_POSITION_X",
    0x36: "ABS_MT_POSITION_Y",
    0x37: "ABS_MT_TOOL_TYPE",
    0x38: "ABS_MT_BLOB_ID",
    0x39: "ABS_MT_TRACKING_ID",
    0x3A: "ABS_MT_PRESSURE",
    0x3B: "ABS_MT_DISTANCE",
    0x3C: "ABS_MT_TOOL_X",
    0x3D: "ABS_MT_TOOL_Y",
}

EV_MSC_CODES = {
    0x00: "MSC_SERIAL",
    0x01: "MSC_PULSELED",
    0x02: "MSC_GESTURE",
    0x03: "MSC_RAW",
    0x04: "MSC_SCAN",
    0x05: "MSC_TIMESTAMP",
}

EV_LED_CODES = {
    0x00: "LED_NUML",
    0x01: "LED_CAPSL",
    0x02: "LED_SCROLLL",
    0x03: "LED_COMPOSE",
    0x04: "LED_KANA",
    0x05: "LED_SLEEP",
    0x06: "LED_SUSPEND",
    0x07: "LED_MUTE",
    0x08: "LED_MISC",
    0x09: "LED_MAIL",
    0x0A: "LED_CHARGING",
}

EV_REP_CODES = {0x00: "REP_DELAY", 0x01: "REP_PERIOD"}

EV_CODE_MAP = {
    0x00: EV_SYN_CODES,
    0x01: EV_KEY_CODES,
    0x02: EV_REL_CODES,
    0x03: EV_ABS_CODES,
    0x04: EV_MSC_CODES,
    0x11: EV_LED_CODES,
    0x14: EV_REP_CODES,
}


def parse_procfs_entry():
    entry_path = "/proc/bus/input/devices"
    devs = []
    with open(entry_path, "r") as info:
        dev_info = {}
        for line in info:
            item = line.rstrip().split(" ", 1)
            if not len(item[0]):  # new section
                devs.append(dev_info)
                dev_info = {}
            elif item[0] == "I:":  # id info
                id_info = {}
                for key_pair in item[1].split(" "):
                    key, val = key_pair.split("=")
                    id_info[key.lower()] = int(val, 16)
                dev_info["id"] = id_info
            elif item[0] == "N:":  # dev name
                val = item[1].split("=", 1)[1]
                dev_info["name"] = val.strip("'\"")
            elif item[0] == "P:":  # phys path
                val = item[1].split("=", 1)[1]
                dev_info["phys"] = val
            elif item[0] == "S:":  # sysfs path
                val = item[1].split("=", 1)[1]
                dev_info["sysfs"] = val
            elif item[0] == "U:":  # unique id
                val = item[1].split("=", 1)[1]
                dev_info["uniq"] = val
            elif item[0] == "H:":  # list of handlers
                val = item[1].split("=", 1)[1]
                dev_info["handlers"] = val.split()
            elif item[0] == "B:":  # bitmaps info
                bitmaps = dev_info.setdefault("bitmaps", {})
                key, val = item[1].split("=", 1)
                bitmaps[key.lower()] = val
    return devs


def open_dev(name):
    path = "/dev/input/%s" % name
    try:
        fd = os.open(path, os.O_RDONLY)
    except Exception as details:
        msg = "could not open device: %s" % str(details)
        error_notify(msg, name)
        sys.exit(-1)
    return fd


def close_dev(fd):
    try:
        os.close(fd)
    except OSError:
        pass


def get_devs():
    entries = {}
    # we are only interested in pointer and keyboard devices
    for info in parse_procfs_entry():
        dev = None
        is_target = False
        for handler in info["handlers"]:
            if handler.startswith("event"):
                dev = handler
            elif handler.startswith("mouse"):
                is_target = True
            elif handler.startswith("kbd"):
                # we assume that a keyboard device must support:
                # EV_SYN, EV_KEY, EV_LED and EV_REP (mask 0x120003)
                hexcode = "0x%s" % info["bitmaps"]["ev"]
                flags = int(hexcode, 16)
                if (~flags & 0x120003) == 0:
                    is_target = True
        if is_target:
            info_notify(dev, info)
            fd = open_dev(dev)
            entries[fd] = (dev, info)
    return entries


def is_graphical_env():
    import subprocess

    child = subprocess.Popen("runlevel", stdout=subprocess.PIPE)
    try:
        stdout = child.communicate()[0]
        runlevel = int(stdout.decode().strip().split()[1])
    except:
        return False
    return runlevel == 5


GRAPHICAL = is_graphical_env()
READY = threading.Event()


if GRAPHICAL:
    os.environ["DISPLAY"] = ":0"

    USING_GI = True
    try:
        import gi

        gi.require_version("Gtk", "3.0")
        from gi.repository import Gdk, GObject, Gtk
    except ImportError:
        USING_GI = False
        import gobject as GObject
        import gtk as Gtk
        import gtk.gdk as Gdk

    class DesktopCover(Gtk.Window):
        def __init__(self):
            super(DesktopCover, self).__init__()
            self.notified = False

            self.set_keep_above(True)
            self.connect("destroy", Gtk.main_quit)
            self.connect("window-state-event", self.on_fullscreen)

            self.label = Gtk.Label("label1")
            self.label.set_text("listening input events")
            self.add(self.label)

            self.fullscreen()
            self.show_all()

        def on_fullscreen(self, window, event):
            global READY
            if USING_GI:
                flag = Gdk.WindowState.FULLSCREEN
            else:
                flag = Gdk.WINDOW_STATE_FULLSCREEN
            if bool(event.new_window_state & flag):
                READY.set()

    def launch_cover():
        GObject.threads_init()
        DesktopCover()
        Gtk.main()


def format_event(raw_event):
    tv_sec, tv_usec, ev_type, ev_code, ev_value = raw_event
    event = {
        "typeNum": ev_type,
        "typeName": EV_TYPES.get(ev_type, "UNKNOWN"),
        "codeNum": ev_code,
        "codeName": EV_CODE_MAP.get(ev_type, {}).get(ev_code, "UNKNOWN"),
        "value": ev_value,
        "timestamp": (tv_sec * (10**6) + tv_usec),
    }
    return event


def listen(devs):
    watch = list(devs.keys())
    while True:
        fds = select.select(watch, (), ())[0]
        for fd in fds:
            dev = devs[fd][0]
            try:
                data = os.read(fd, EV_PACK_SIZE)
                raw_event = struct.unpack(EV_PACK_FMT, data)
            except Exception as details:
                msg = "failed to get event: %s" % str(details)
                error_notify(msg, dev)
                watch.remove(fd)
            event = format_event(raw_event)
            event_notify(dev, event)
        if not watch:
            break


def setup():
    devs = get_devs()
    if GRAPHICAL:
        threading.Thread(target=launch_cover).start()
    else:
        READY.set()
    READY.wait()
    ready_notify()
    return devs


def cleanup(devs):
    for fd in devs.keys():
        close_dev(fd)
    if GRAPHICAL:
        Gtk.main_quit()


def main_loop():
    global READY

    sync_notify()
    devs = setup()
    try:
        listen(devs)
    except KeyboardInterrupt:
        pass
    finally:
        cleanup(devs)


if __name__ == "__main__":
    main_loop()
