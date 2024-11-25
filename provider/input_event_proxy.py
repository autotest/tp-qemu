import json
import logging
import os
from queue import Queue

from virttest import data_dir, utils_misc

LOG_JOB = logging.getLogger("avocado.test")


DEP_DIR = data_dir.get_deps_dir("input_event")


class AgentMessageType:
    """Agent message types."""

    SYNC = "SYNC"
    INFO = "INFO"
    READY = "READY"
    EVENT = "EVENT"
    ERROR = "ERROR"


class AgentState:
    """Agent state codes."""

    STOPPED = 0
    GREETING = 1
    LISTENING = 2


EventTypeKey = "type"
DevNameKey = "device"


class EventType:
    """Event types."""

    KEYDOWN = "KEYDOWN"
    KEYUP = "KEYUP"
    POINTERMOVE = "POINTERMOVE"
    WHEELFORWARD = "WHEELFORWARD"
    WHEELBACKWARD = "WHEELBACKWARD"
    UNKNOWN = "UNKNOWN"


class KeyEventData:
    """Key event schema."""

    KEYCODE = "keyCode"
    SCANCODE = "scanCode"


class PointerEventData:
    """Pointer event schema."""

    XPOS = "xPos"
    YPOS = "yPos"
    ABS = "abs"


class WheelEventData:
    """Wheel event schema."""

    HSCROLL = "hScroll"  # horizontal scroll wheel
    ABS = "abs"


class _EventListener(object):
    """Base implementation for the event listener class."""

    agent_source = ""
    agent_target = ""
    python_bin = ""

    def __init__(self, vm):
        """
        Initialize the event listener.

        :param vm: VM object.
        """
        self.events = Queue()
        self.targets = {}
        self._vm = vm
        self._ctrl_sh = vm.wait_for_login()
        self._agent_sh = None
        self._agent_state = AgentState.STOPPED
        self._install()
        self._listen()

    def _install(self):
        """Install (copy) the agent into VM."""
        if not os.path.exists(self.agent_source):
            raise IOError("agent program is missing")
        self._vm.copy_files_to(self.agent_source, self.agent_target)

    def _uninstall(self):
        """Uninstall the agent."""
        raise NotImplementedError()

    def _launch(self):
        """Launch the agent."""
        self._agent_sh = self._vm.wait_for_login()
        self._agent_sh.set_output_func(self._parse_output)
        self._agent_sh.set_output_params(tuple())
        cmd = " ".join((self.python_bin, self.agent_target))
        self._agent_sh.sendline(cmd)

    def _terminate(self):
        """Terminate the agent."""
        self._agent_sh.sendcontrol("c")
        self._agent_sh.close()
        # session objects wants `output_func` to be serializable,
        # but it does not make sense currently, drop the value to
        # avoid the framework complainting about that.
        self._agent_sh.set_output_func(None)
        self._agent_sh = None
        self._agent_state = AgentState.STOPPED
        LOG_JOB.info("Stopped listening input events on %s", self._vm.name)

    def is_listening(self):
        """Return `True` if listening."""
        return self._agent_state == AgentState.LISTENING

    def _listen(self):
        """Listen events in VM."""
        self._launch()
        if not utils_misc.wait_for(self.is_listening, timeout=10, step=1):
            raise AssertionError("agent program is not running")
        LOG_JOB.info("Listening input events on %s", self._vm.name)

    def cleanup(self):
        """Cleanup the event listener."""
        self._terminate()
        self._uninstall()
        self._ctrl_sh.close()

    def clear_events(self):
        """Clear all the queued events."""
        while not self.events.empty():
            self.events.get()

    def _parse_output(self, line):
        """Parse output of the agent."""
        try:
            message = json.loads(line)
        except:
            # garbage line, skip it
            return
        mtype = message["type"]
        content = message["content"]
        if mtype == AgentMessageType.SYNC:
            self._agent_state = AgentState.GREETING
        elif mtype == AgentMessageType.INFO:
            self._report_info(content)
        elif mtype == AgentMessageType.READY:
            self._agent_state = AgentState.LISTENING
        elif mtype == AgentMessageType.EVENT:
            self._parse_platform_event(content)
        elif mtype == AgentMessageType.ERROR:
            self._report_error(content)
        else:
            LOG_JOB.error("Input event listener received unknown message")

    def _report_info(self, content):
        """Report information of devices."""
        dev = content["device"]
        info = content["info"]
        self.targets[dev] = info

    def _report_error(self, content):
        """Report errors."""
        pass

    def _parse_platform_event(self, content):
        """Parse events of the certian platform."""
        raise NotImplementedError()


class EventListenerLinux(_EventListener):
    """Linux implementation for the event listener class."""

    agent_source = os.path.join(DEP_DIR, "input_event_linux.py")
    agent_target = "/tmp/input_event.py"
    python_bin = "`command -v python python3 | head -1`"

    KEYDOWN = 1
    KEYUP = 0

    WHEELFORWARD = 0x00000001
    WHEELBACKWARD = 0xFFFFFFFF

    def __init__(self, vm):
        super(EventListenerLinux, self).__init__(vm)
        self._buffers = {}

    def _uninstall(self):
        cmd = " ".join(("rm", "-f", self.agent_target))
        self._ctrl_sh.cmd(cmd, ignore_all_errors=True)

    def _report_info(self, content):
        super(EventListenerLinux, self)._report_info(content)
        dev = content["device"]
        self._buffers[dev] = {}

    def _parse_platform_event(self, content):
        dev = content["device"]
        nevent = content["event"]
        etype = nevent["typeName"]
        value = nevent["value"]
        ebuf = self._buffers[dev]
        if etype == "EV_SYN":
            subtype = nevent["codeName"]
            if subtype == "SYN_REPORT":
                # end of event, report it
                ebuf[DevNameKey] = dev
                self.events.put(ebuf)
                ebuf = {EventTypeKey: EventType.UNKNOWN}
        elif etype == "EV_KEY":
            keycode = nevent["codeName"]
            if value == self.KEYDOWN:
                mtype = EventType.KEYDOWN
            elif value == self.KEYUP:
                mtype = EventType.KEYUP
            else:
                mtype = value
            if mtype:
                ebuf[EventTypeKey] = mtype
            ebuf[KeyEventData.KEYCODE] = keycode
        elif etype == "EV_REL":
            subtype = nevent["codeName"]
            if subtype in ("REL_X", "REL_Y"):
                ebuf[EventTypeKey] = EventType.POINTERMOVE
                if subtype.endswith("X"):
                    ebuf[PointerEventData.XPOS] = value
                else:  # 'Y'
                    ebuf[PointerEventData.YPOS] = value
                ebuf[PointerEventData.ABS] = 0
            elif subtype in ("REL_HWHEEL", "REL_WHEEL"):
                if value == self.WHEELFORWARD:
                    ebuf[EventTypeKey] = EventType.WHEELFORWARD
                elif value == self.WHEELBACKWARD:
                    ebuf[EventTypeKey] = EventType.WHEELBACKWARD
                if subtype.endswith("HWHEEL"):
                    ebuf[WheelEventData.HSCROLL] = 1
                else:
                    ebuf[WheelEventData.HSCROLL] = 0
                ebuf[WheelEventData.ABS] = 0
        elif etype == "EV_ABS":
            subtype = nevent["codeName"]
            if subtype in ("ABS_X", "ABS_Y"):
                ebuf[EventTypeKey] = EventType.POINTERMOVE
                if subtype.endswith("X"):
                    ebuf[PointerEventData.XPOS] = value
                else:  # 'Y'
                    ebuf[PointerEventData.YPOS] = value
                ebuf[PointerEventData.ABS] = 1
            elif subtype == "ABS_WHEEL":
                if value == self.WHEELFORWARD:
                    ebuf[EventTypeKey] = EventType.WHEELFORWARD
                elif value == self.WHEELBACKWARD:
                    ebuf[EventTypeKey] = EventType.WHEELBACKWARD
                ebuf[WheelEventData.HSCROLL] = 0
                ebuf[WheelEventData.ABS] = 1
        elif etype == "EV_MSC":
            subtype = nevent["codeName"]
            if subtype == "MSC_SCAN":
                ebuf[KeyEventData.SCANCODE] = value
        elif etype == "EV_LED":
            # TODO: handle this kind of events when necessary
            pass
        elif etype == "EV_REP":
            # FIXME: handle this kind of events
            pass
        else:
            ebuf[EventTypeKey] = EventType.UNKNOWN
        self._buffers[dev] = ebuf


# XXX: we may need different map tables for different keyboard layouts,
# or even the best solution is not using any mapping, but let us pick
# the current implementation since I can only realize this.
UNMAPPED = "UNMAPPED"
VK2Linux = {
    "VK_BACK": "KEY_BACKSPACE",
    "VK_TAB": "KEY_TAB",
    "VK_CLEAR": "KEY_CLEAR",
    "VK_RETURN": "KEY_ENTER",
    "VK_SHIFT": "KEY_LEFTSHIFT",
    "VK_CONTROL": "KEY_LEFTCTRL",
    "VK_MENU": "KEY_LEFTALT",
    "VK_PAUSE": "KEY_PAUSE",
    "VK_CAPITAL": "KEY_CAPSLOCK",
    "VK_KANA": "KEY_KATAKANA",
    "VK_HANGUEL": "KEY_HANGEUL",
    "VK_HANGUL": "KEY_HANGEUL",
    "VK_JUNJA": UNMAPPED,
    "VK_FINAL": UNMAPPED,
    "VK_HANJA": "KEY_HANJA",
    "VK_KANJI": UNMAPPED,
    "VK_ESCAPE": "KEY_ESC",
    "VK_CONVERT": "KEY_HENKAN",
    "VK_NONCONVERT": "KEY_MUHENKAN",
    "VK_ACCEPT": UNMAPPED,
    "VK_MODECHANGE": UNMAPPED,
    "VK_SPACE": "KEY_SPACE",
    "VK_PRIOR": "KEY_PAGEUP",
    "VK_NEXT": "KEY_PAGEDOWN",
    "VK_END": "KEY_END",
    "VK_HOME": "KEY_HOME",
    "VK_LEFT": "KEY_LEFT",
    "VK_UP": "KEY_UP",
    "VK_RIGHT": "KEY_RIGHT",
    "VK_DOWN": "KEY_DOWN",
    "VK_SELECT": "KEY_SELECT",
    "VK_PRINT": "KEY_PRINT",
    "VK_EXECUTE": UNMAPPED,
    "VK_SNAPSHOT": "KEY_SYSRQ",
    "VK_INSERT": "KEY_INSERT",
    "VK_DELETE": "KEY_DELETE",
    "VK_HELP": "KEY_HELP",
    "VK_0": "KEY_0",
    "VK_1": "KEY_1",
    "VK_2": "KEY_2",
    "VK_3": "KEY_3",
    "VK_4": "KEY_4",
    "VK_5": "KEY_5",
    "VK_6": "KEY_6",
    "VK_7": "KEY_7",
    "VK_8": "KEY_8",
    "VK_9": "KEY_9",
    "VK_A": "KEY_A",
    "VK_B": "KEY_B",
    "VK_C": "KEY_C",
    "VK_D": "KEY_D",
    "VK_E": "KEY_E",
    "VK_F": "KEY_F",
    "VK_G": "KEY_G",
    "VK_H": "KEY_H",
    "VK_I": "KEY_I",
    "VK_J": "KEY_J",
    "VK_K": "KEY_K",
    "VK_L": "KEY_L",
    "VK_M": "KEY_M",
    "VK_N": "KEY_N",
    "VK_O": "KEY_O",
    "VK_P": "KEY_P",
    "VK_Q": "KEY_Q",
    "VK_R": "KEY_R",
    "VK_S": "KEY_S",
    "VK_T": "KEY_T",
    "VK_U": "KEY_U",
    "VK_V": "KEY_V",
    "VK_W": "KEY_W",
    "VK_X": "KEY_X",
    "VK_Y": "KEY_Y",
    "VK_Z": "KEY_Z",
    "VK_LWIN": "KEY_LEFTMETA",
    "VK_RWIN": "KEY_RIGHTMETA",
    "VK_APPS": "KEY_COMPOSE",
    "VK_SLEEP": "KEY_SLEEP",
    "VK_NUMPAD0": "KEY_KP0",
    "VK_NUMPAD1": "KEY_KP1",
    "VK_NUMPAD2": "KEY_KP2",
    "VK_NUMPAD3": "KEY_KP3",
    "VK_NUMPAD4": "KEY_KP4",
    "VK_NUMPAD5": "KEY_KP5",
    "VK_NUMPAD6": "KEY_KP6",
    "VK_NUMPAD7": "KEY_KP7",
    "VK_NUMPAD8": "KEY_KP8",
    "VK_NUMPAD9": "KEY_KP9",
    "VK_MULTIPLY": "KEY_KPASTERISK",
    "VK_ADD": "KEY_KPPLUS",
    "VK_SEPARATOR": "KEY_KPCOMMA",
    "VK_SUBTRACT": "KEY_KPMINUS",
    "VK_DECIMAL": "KEY_KPDOT",
    "VK_DIVIDE": "KEY_KPSLASH",
    "VK_F1": "KEY_F1",
    "VK_F2": "KEY_F2",
    "VK_F3": "KEY_F3",
    "VK_F4": "KEY_F4",
    "VK_F5": "KEY_F5",
    "VK_F6": "KEY_F6",
    "VK_F7": "KEY_F7",
    "VK_F8": "KEY_F8",
    "VK_F9": "KEY_F9",
    "VK_F10": "KEY_F10",
    "VK_F11": "KEY_F11",
    "VK_F12": "KEY_F12",
    "VK_F13": "KEY_F13",
    "VK_F14": "KEY_F14",
    "VK_F15": "KEY_F15",
    "VK_F16": "KEY_F16",
    "VK_F17": "KEY_F17",
    "VK_F18": "KEY_F18",
    "VK_F19": "KEY_F19",
    "VK_F20": "KEY_F20",
    "VK_F21": "KEY_F21",
    "VK_F22": "KEY_F22",
    "VK_F23": "KEY_F23",
    "VK_F24": "KEY_F24",
    "VK_NUMLOCK": "KEY_NUMLOCK",
    "VK_SCROLL": "KEY_SCROLLLOCK",
    "VK_OEM_0x92": UNMAPPED,
    "VK_OEM_0x93": UNMAPPED,
    "VK_OEM_0x94": UNMAPPED,
    "VK_OEM_0x95": UNMAPPED,
    "VK_OEM_0x96": UNMAPPED,
    "VK_LSHIFT": "KEY_LEFTSHIFT",
    "VK_RSHIFT": "KEY_RIGHTSHIFT",
    "VK_LCONTROL": "KEY_LEFTCTRL",
    "VK_RCONTROL": "KEY_RIGHTCTRL",
    "VK_LMENU": "KEY_LEFTALT",
    "VK_RMENU": "KEY_RIGHTALT",
    "VK_BROWSER_BACK": "KEY_BACK",
    "VK_BROWSER_FORWARD": "KEY_FORWARD",
    "VK_BROWSER_REFRESH": "KEY_REFRESH",
    "VK_BROWSER_STOP": "KEY_STOP",
    "VK_BROWSER_SEARCH": "KEY_SEARCH",
    "VK_BROWSER_FAVORITES": "KEY_FAVORITES",
    "VK_BROWSER_HOME": "KEY_HOMEPAGE",
    "VK_VOLUME_MUTE": "KEY_MUTE",
    "VK_VOLUME_DOWN": "KEY_VOLUMEDOWN",
    "VK_VOLUME_UP": "KEY_VOLUMEUP",
    "VK_MEDIA_NEXT_TRACK": "KEY_NEXTSONG",
    "VK_MEDIA_PREV_TRACK": "KEY_PREVIOUSSONG",
    "VK_MEDIA_STOP": "KEY_STOPCD",
    "VK_MEDIA_PLAY_PAUSE": "KEY_PLAYPAUSE",
    "VK_LAUNCH_MAIL": "KEY_EMAIL",
    "VK_LAUNCH_MEDIA_SELECT": UNMAPPED,
    "VK_LAUNCH_APP1": UNMAPPED,
    "VK_LAUNCH_APP2": UNMAPPED,
    "VK_OEM_1": "KEY_SEMICOLON",
    "VK_OEM_PLUS": "KEY_EQUAL",
    "VK_OEM_COMMA": "KEY_COMMA",
    "VK_OEM_MINUS": "KEY_MINUS",
    "VK_OEM_PERIOD": "KEY_DOT",
    "VK_OEM_2": "KEY_SLASH",
    "VK_OEM_3": "KEY_GRAVE",
    "VK_OEM_4": "KEY_LEFTBRACE",
    "VK_OEM_5": "KEY_BACKSLASH",
    "VK_OEM_6": "KEY_RIGHTBRACE",
    "VK_OEM_7": "KEY_APOSTROPHE",
    "VK_OEM_8": UNMAPPED,
    "VK_OEM_0xE1": UNMAPPED,
    "VK_OEM_102": "KEY_102ND",
    "VK_OEM_0xE3": UNMAPPED,
    "VK_OEM_0xE4": UNMAPPED,
    "VK_PROCESSKEY": UNMAPPED,
    "VK_OEM_0xE6": UNMAPPED,
    "VK_PACKET": UNMAPPED,
    "VK_OEM_0xE9": UNMAPPED,
    "VK_OEM_0xEA": UNMAPPED,
    "VK_OEM_0xEB": UNMAPPED,
    "VK_OEM_0xEC": UNMAPPED,
    "VK_OEM_0xED": UNMAPPED,
    "VK_OEM_0xEE": UNMAPPED,
    "VK_OEM_0xEF": UNMAPPED,
    "VK_OEM_0xF0": UNMAPPED,
    "VK_OEM_0xF1": UNMAPPED,
    "VK_OEM_0xF2": UNMAPPED,
    "VK_OEM_0xF3": UNMAPPED,
    "VK_OEM_0xF4": UNMAPPED,
    "VK_OEM_0xF5": UNMAPPED,
    "VK_ATTN": UNMAPPED,
    "VK_CRSEL": UNMAPPED,
    "VK_EXSEL": UNMAPPED,
    "VK_EREOF": UNMAPPED,
    "VK_PLAY": "KEY_PLAY",
    "VK_ZOOM": "KEY_ZOOM",
    "VK_NONAME": UNMAPPED,
    "VK_PA1": UNMAPPED,
    "VK_OEM_CLEAR": UNMAPPED,
}


class EventListenerWin(_EventListener):
    """Windows implementation for the event listener class."""

    agent_source = os.path.join(DEP_DIR, "input_event_win.py")
    agent_target = r"%TEMP%\input_event.py"
    python_bin = "python"

    def _uninstall(self):
        cmd = " ".join(("del", self.agent_target))
        self._ctrl_sh.cmd(cmd, ignore_all_errors=True)

    def _parse_platform_event(self, content):
        dev = content["device"]
        nevent = content["event"]
        etype = nevent["typeName"]
        event = {}
        mtype = EventType.UNKNOWN
        if etype in ("WM_KEYDOWN", "WM_KEYUP", "WM_SYSKEYDOWN", "WM_SYSKEYUP"):
            keycode = VK2Linux[nevent["vkCodeName"]]
            scancode = nevent["scanCode"]
            if etype.endswith("DOWN"):
                mtype = EventType.KEYDOWN
            else:  # 'UP'
                mtype = EventType.KEYUP
            event[KeyEventData.KEYCODE] = keycode
            event[KeyEventData.SCANCODE] = scancode
        elif etype in (
            "WM_LBUTTONDOWN",
            "WM_LBUTTONUP",
            "WM_RBUTTONDOWN",
            "WM_RBUTTONUP",
            "WM_MBUTTONDOWN",
            "WM_MBUTTONUP",
            "WM_XBUTTONDOWN",
            "WM_XBUTTONUP",
        ):
            if etype.endswith("DOWN"):
                mtype = EventType.KEYDOWN
            else:  # 'UP'
                mtype = EventType.KEYUP
            button = etype[3]
            if button == "L":
                keycode = "BTN_LEFT"
            elif button == "R":
                keycode = "BTN_RIGHT"
            elif button == "M":
                keycode = "BTN_MIDDLE"
            else:  # 'X'
                xbutton = nevent["mouseDataText"]
                if xbutton == "XBUTTON1":
                    keycode = "BTN_SIDE"
                elif xbutton == "XBUTTON2":
                    keycode = "BTN_EXTRA"
                else:
                    keycode = xbutton
            event[KeyEventData.KEYCODE] = keycode
        elif etype in ("WM_MOUSEWHEEL", "WM_MOUSEHWHEEL"):
            direction = nevent["mouseDataText"]
            if direction == "WHEELFORWARD":
                mtype = EventType.WHEELFORWARD
            elif direction == "WHEELBACKWARD":
                mtype = EventType.WHEELBACKWARD
            if etype.endswith("MOUSEHWHEEL"):
                event[WheelEventData.HSCROLL] = 1
            else:
                event[WheelEventData.HSCROLL] = 0
        elif etype == "WM_MOUSEMOVE":
            xpos = nevent["xPos"]
            ypos = nevent["yPos"]
            mtype = EventType.POINTERMOVE
            event[PointerEventData.XPOS] = xpos
            event[PointerEventData.YPOS] = ypos
        event[EventTypeKey] = mtype
        event[DevNameKey] = dev
        self.events.put(event)


def EventListener(vm):
    """
    Event listener factory. This function creates an event listener
    instance by respecting the OS type of the given VM.

    :param vm: VM object.

    :return: Event listener object.
    """
    klass = None
    os_type = vm.params["os_type"]
    if os_type == "linux":
        klass = EventListenerLinux
    elif os_type == "windows":
        klass = EventListenerWin
    if not klass:
        raise ValueError("unsupported guest os type")
    return klass(vm)
