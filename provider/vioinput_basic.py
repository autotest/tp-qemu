import json
import os
import time

from virttest import data_dir, error_context, graphical_console

from provider import input_event_proxy


def get_keycode_cfg(filename):
    """
    Get keyname to keycode cfg table.
    :param filename: filename that key to keycode file.
    """
    keycode_cfg_path = os.path.join(data_dir.get_deps_dir("key_keycode"), filename)
    print(keycode_cfg_path)
    with open(keycode_cfg_path) as f:
        return json.load(f)


@error_context.context_aware
def key_tap_test(test, params, vm):
    """
    Keyboard test. Support single key and combination key tests.

    :param test: kvm test object
    :param params: dictionary with the test parameters
    :param vm: vm object
    """

    def key_check(key):
        """
        Check received key event match exepected key event.
        :param key: tested key name.
        """
        events_queue = listener.events

        if "-" in key:
            key_lst = [key_check_cfg[k] for k in key.split("-")]
        else:
            key_lst = [key_check_cfg[key]]
        key_num = len(key_lst)
        key_event_lst = list()

        while not events_queue.empty():
            events = events_queue.get()
            key_event_lst.append((events["keyCode"], events["type"]))

        if len(key_event_lst) < 2 * key_num:
            test.fail("Reveived key events %s were not enough" % key_event_lst)

        key_down_lst = list()
        for k, v in key_event_lst[:-key_num]:
            if v != "KEYDOWN":
                test.fail("Received key {0} event type {1} was not KEYDOWN").format(
                    k, v
                )
            key_down_lst.append(k)

        if len(key_down_lst) != key_num or set(key_down_lst) != set(key_lst):
            test.fail(
                "Key down event keycode error, received:{0}," "expect:{1}"
            ).format(key_down_lst, key_lst)

        key_up_lst = list()
        for k, v in key_event_lst[-key_num:]:
            if v != "KEYUP":
                test.fail("Received key {0} event type {1} was not KEYUP").format(k, v)
            key_up_lst.append(k)

        if set(key_up_lst) != set(key_lst):
            test.fail("Key up event keycode error, received:{0}," "expect:{1}").format(
                key_up_lst, key_lst
            )

    key_table_file = params.get("key_table_file")
    key_check_cfg = get_keycode_cfg(key_table_file)
    wait_time = float(params.get("wait_time", 0.2))

    error_context.context("Start event listener in guest", test.log.info)
    listener = input_event_proxy.EventListener(vm)

    console = graphical_console.GraphicalConsole(vm)
    for key in key_check_cfg.keys():
        error_context.context("Send %s key tap to guest" % key, test.log.info)
        console.key_tap(key)
        error_context.context(
            "Check %s key tap event received" "correct in guest" % key, test.log.info
        )
        time.sleep(wait_time)
        key_check(key)

    listener.clear_events()
    listener.cleanup()
