"""Input test related functions"""

import json
import logging
import os
import time
from collections import Counter

from virttest import data_dir, error_context, graphical_console

from provider import input_event_proxy

LOG_JOB = logging.getLogger("avocado.test")


def get_keycode_cfg(filename):
    """
    Get keyname to keycode cfg table.

    :param filename: filename that key to keycode file.
    """

    keycode_cfg_path = os.path.join(data_dir.get_deps_dir("key_keycode"), filename)
    with open(keycode_cfg_path) as f:
        return json.load(f)


@error_context.context_aware
def key_tap_test(test, params, console, listener, wait_time):
    """
    key tap test, single key press and release.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param console: graphical console.
    :param listener: listening the mouse button event in guest.
    :param keys_file: a file include all tested keys.
    :param wait_time: wait event received in listener event queue.
    """

    keys_file = params.get("key_table_file")
    keys_dict = get_keycode_cfg(keys_file)
    for key in keys_dict.keys():
        error_context.context("Send %s key tap event" % key, LOG_JOB.info)
        console.key_tap(key)
        time.sleep(wait_time)

        LOG_JOB.info(
            "Check guest received %s key event is " "matched with expected key event",
            key,
        )
        keycode = keys_dict[key]
        exp_events = [(keycode, "KEYDOWN"), (keycode, "KEYUP")]
        event_queue = listener.events
        key_events = []
        while not event_queue.empty():
            event = event_queue.get()
            if event["type"] == "POINTERMOVE":
                continue
            key_events.append((event["keyCode"], event["type"]))

        if key_events != exp_events:
            test.fail(
                "Received key event didn't match expected event.\n"
                "Received key event as: %s\n Expected event as: %s"
                % (key_events, exp_events)
            )


@error_context.context_aware
def mouse_btn_test(test, params, console, listener, wait_time):
    """
    Mouse button test, include button: left, right, middle, side, extra.
    Only do single button test here.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param console: graphical console.
    :param listener: listening the mouse button event in guest.
    :param wait_time: wait event received in listener event queue.
    """
    mouse_btn_map = {
        "left": "BTN_LEFT",
        "right": "BTN_RIGHT",
        "middle": "BTN_MIDDLE",
        "side": "BTN_SIDE",
        "extra": "BTN_EXTRA",
    }
    btns = params.objects("btns")
    for btn in btns:
        error_context.context("Click mouse %s button" % btn, LOG_JOB.info)
        console.btn_click(btn)

        keycode = mouse_btn_map[btn]
        exp_events = [(keycode, "KEYDOWN"), (keycode, "KEYUP")]
        time.sleep(wait_time)
        events_queue = listener.events
        btn_event = list()

        error_context.context("Check correct button event is received", LOG_JOB.info)
        while not events_queue.empty():
            events = events_queue.get()
            # some windows os will return pointer move event first
            # before return btn event, so filter them here.
            if events["type"] == "POINTERMOVE":
                continue
            btn_event.append((events["keyCode"], events["type"]))

        if btn_event != exp_events:
            test.fail(
                "Received btn events don't match expected events.\n"
                "Received btn events as: %s\n Expected events as: %s"
                % (btn_event, exp_events)
            )


@error_context.context_aware
def mouse_scroll_test(test, params, console, listener, wait_time, count=1):
    """
    Mouse scroll test.

    :param test: kvm test object.
    :param params: Dictionary with the test parameters
    :param console: graphical console.
    :param listener: listening the mouse button event in guest.
    :param wait_time: wait event received in listener event queue.
    :param count: wheel event counts, default count=1.
    """
    scrolls = params.objects("scrolls")
    exp_events = {"wheel-up": ("WHEELFORWARD", 0), "wheel-down": ("WHEELBACKWARD", 0)}
    for scroll in scrolls:
        error_context.context("Scroll mouse %s" % scroll, LOG_JOB.info)
        if "up" in scroll:
            console.scroll_forward(count)
        else:
            console.scroll_backward(count)

        events_queue = listener.events
        time.sleep(wait_time)
        error_context.context("Check correct scroll event is received", LOG_JOB.info)
        exp_event = exp_events.get(scroll)
        samples = []
        while not events_queue.empty():
            event = events_queue.get()
            # some windows os will return pointer move event first
            # before return scroll event, so filter them here.
            if event["type"] == "POINTERMOVE":
                continue
            samples.append((event["type"], event["hScroll"]))

        counter = Counter(samples)
        num = counter.pop(exp_event, 0)
        if num != count:
            test.fail(
                "Received scroll number %s don't match expected"
                "scroll count %s" % (num, count)
            )
        if counter:
            test.fail(
                "Received scroll events don't match expected events"
                "Received scroll events as: %s\n Expected events as: %s"
                % (counter, exp_event)
            )


@error_context.context_aware
def mouse_move_test(test, params, console, listener, wait_time, end_pos, absolute):
    """
    Mouse move test, default move trace is uniform linear motion.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param console: graphical console.
    :param listener: listening the mouse button event in guest.
    :param wait_time: wait event received in listener event queue.
    :param end_pos: a tuple of mouse destination position.
    :param absolute: Mouse move type is absolute or relative.
    """
    move_rate = int(params.get("move_rate", 80))
    move_duration = int(params.get("move_duration", 1))
    line = graphical_console.uniform_linear(move_duration, move_rate)
    width, height = console.screen_size
    events_queue = listener.events
    event_lst = []
    start_pos = console.pointer_pos
    x0, y0 = start_pos
    xn, yn = end_pos
    # Compute a line y=kx+b through start_pos and end_pos.
    if (xn - x0) != 0:
        vertical = 0
        k = (yn - y0) / (xn - x0)
        b = yn - (k * xn)
    else:
        vertical = 1

    error_context.context(
        "Moving pointer from %s to %s" % (start_pos, end_pos), LOG_JOB.info
    )
    console.pointer_move(end_pos, motion=line, absolute=absolute)
    time.sleep(wait_time)

    error_context.context("Collecting all pointer move events from guest", LOG_JOB.info)
    while not events_queue.empty():
        event = events_queue.get()
        xpos, ypos = event["xPos"], event["yPos"]
        # Filter beyond screen size events.
        # Due to os will ignores/corrects these events.
        if 0 <= xpos <= width and 0 <= ypos <= height:
            event_lst.append((event["xPos"], event["yPos"]))

    xn_guest, yn_guest = event_lst[-1]
    tolerance = int(params.get("tolerance"))
    error_context.context(
        "Compare if pointer move to destination pos (%s, %s)"
        "the missed value should in tolerance scope." % end_pos,
        LOG_JOB.info,
    )
    if (abs(xn - xn_guest) > tolerance) or (abs(yn - yn_guest) > tolerance):
        test.fail(
            "pointer did not move to destination position."
            "it move to pos (%s, %s) in guest, but exepected pos is"
            "(%s, %s)" % (xn_guest, yn_guest, xn, yn)
        )

    error_context.context(
        "Compare if pointer move trace nearby destination line,"
        "the missed value should in tolerance scope.",
        LOG_JOB.info,
    )

    for i, (x, y) in enumerate(event_lst):
        if not vertical:
            if abs((k * x + b) - y) > tolerance:  # pylint: disable=E0606
                test.fail(
                    "Received pointer pos beyond line's tolerance scope "
                    "when move from {0} to {1}. Received pos is ({2}, {3}),"
                    "it didn't nearby the expected line "
                    "y={4}x+{5}.".format(start_pos, end_pos, x, y, k, b)
                )
            elif k == 0:
                # for horizontal direction line, only x value will change.
                if i > 0:
                    dx = [x2 - x1 for x1, x2 in zip(event_lst[i - 1], event_lst[i])][0]
                    if xn - x0 > 0 and dx <= 0:
                        test.fail(
                            "pointer move direction is wrong when "
                            "move from {0} to {1}.".format(start_pos, end_pos)
                        )
                    elif xn - x0 < 0 and dx >= 0:
                        test.fail(
                            "pointer move direction is wrong when "
                            "move from {0} to {1}.".format(start_pos, end_pos)
                        )
        else:
            # for vertical direction line, only y value will change.
            if i > 0:
                dy = [y2 - y1 for y1, y2 in zip(event_lst[i - 1], event_lst[i])][1]
                if (yn - y0 > 0 and dy <= 0) or (yn - y0 < 0 and dy >= 0):
                    test.fail(
                        "pointer move to incorrect direction when "
                        "move from {0} to {1}.".format(start_pos, end_pos)
                    )


def query_mice_status(vm, mice_name):
    """
    Query which mice enabled currently in guest.

    :param vm: VM object
    :param mice_name: query mice name
    """
    events = vm.monitor.query_mice()
    for event in events:
        if event["name"] == mice_name:
            return event


def keyboard_test(test, params, vm, wait_time):
    """
    Keyboard tests, only include key_tap_test currently.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param vm: VM object
    :param wait_time: wait event received in listener event queue.
    """
    console = graphical_console.GraphicalConsole(vm)
    listener = input_event_proxy.EventListener(vm)
    key_tap_test(test, params, console, listener, wait_time)
    listener.clear_events()
    listener.cleanup()


def mouse_test(test, params, vm, wait_time, count=1):
    """
    Mouse test, include button test, scroll test and move test.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param vm: VM object
    :param wait_time: wait event received in listener event queue.
    :param count: wheel event counts, default count=1.
    """
    console = graphical_console.GraphicalConsole(vm)
    listener = input_event_proxy.EventListener(vm)
    mice_name = params.get("mice_name", "QEMU PS/2 Mouse")
    mice_info = query_mice_status(vm, mice_name)
    absolute = True if mice_info["absolute"] else False
    error_context.context("Check if %s device is working" % mice_name, LOG_JOB.info)
    if not mice_info["current"]:
        test.fail("%s does not worked currently" % mice_name)

    mouse_btn_test(test, params, console, listener, wait_time)
    mouse_scroll_test(test, params, console, listener, wait_time, count=count)
    if not params.get("target_pos", None):
        width, height = console.screen_size
        x_max, y_max = width - 1, height - 1
        target_pos = [(1, 0), (x_max, 0), (1, y_max), (x_max, y_max)]
    else:
        # suggest set target_pos if want to test one target position.
        target_pos = [tuple([int(i) for i in params.objects("target_pos")])]
    for end_pos in target_pos:
        mouse_move_test(test, params, console, listener, wait_time, end_pos, absolute)
    listener.clear_events()
    listener.cleanup()
