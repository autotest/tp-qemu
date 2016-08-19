import logging
import time
import commands

from autotest.client.shared import error

from virttest import utils_misc


def run(test, params, env):
    """
    Test qmp event notification function:
    1) Boot up guest with qmp.
    2) Trigger qmp event in guest.
    3) Try to catch qmp event notification in qmp monitor.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """

    qemu_binary = utils_misc.get_qemu_binary(params)
    if not utils_misc.qemu_has_option("qmp", qemu_binary):
        error.TestNAError("This test case requires a host QEMU with QMP "
                          "monitor support")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    qmp_monitor = filter(lambda x: x.protocol == "qmp", vm.monitors)[0]
    humam_monitor = filter(lambda x: x.protocol == "human", vm.monitors)[0]
    callback = {"host_cmd": commands.getoutput,
                "guest_cmd": session.cmd,
                "monitor_cmd": humam_monitor.send_args_cmd,
                "qmp_cmd": qmp_monitor.send_args_cmd}

    def send_cmd(cmd, cmd_type, options={}):
        if cmd_type in callback.keys():
            return callback[cmd_type](cmd, **options)
        else:
            raise error.TestError("cmd_type is not supported")

    cmd_type = params["event_cmd_type"]
    pre_event_cmd = params.get("pre_event_cmd", "")
    pre_event_cmd_type = params.get("pre_event_cmd_type", cmd_type)
    pre_event_cmd_options = eval(
        "dict({0})".format(params.get("pre_event_cmd_options", "")))
    event_cmd = params.get("event_cmd")
    event_cmd_options = eval(
        "dict({0})".format(params.get("event_cmd_options", "")))
    post_event_cmd = params.get("post_event_cmd", "")
    post_event_cmd_type = params.get("post_event_cmd_type", cmd_type)
    post_event_cmd_options = eval(
        "dict({0})".format(params.get("post_event_cmd_options", "")))
    event_check = params.get("event_check")
    timeout = int(params.get("check_timeout", 360))
    action_check = params.get("action_check")

    if pre_event_cmd:
        send_cmd(pre_event_cmd, pre_event_cmd_type,
                 pre_event_cmd_options)

    send_cmd(event_cmd, cmd_type, event_cmd_options)

    end_time = time.time() + timeout
    qmp_monitors = vm.get_monitors_by_type("qmp")
    qmp_num = len(qmp_monitors)
    logging.info("Try to get qmp events in %s seconds!", timeout)
    while time.time() < end_time:
        for monitor in qmp_monitors:
            event = monitor.get_event(event_check)
            if event_check == "WATCHDOG":
                if event and event['data']['action'] == action_check:
                    logging.info("Receive watchdog %s event notification",
                                 action_check)
                    qmp_num -= 1
                    qmp_monitors.remove(monitor)
            else:
                if event:
                    logging.info("Receive qmp %s event notification",
                                 event_check)
                    qmp_num -= 1
                    qmp_monitors.remove(monitor)
        time.sleep(5)
        if qmp_num <= 0:
            break

    if qmp_num > 0:
        raise error.TestFail("Did not receive qmp %s event notification"
                             % event_check)

    if post_event_cmd:
        send_cmd(post_event_cmd, post_event_cmd_type,
                 post_event_cmd_options)
    if session:
        session.close()
