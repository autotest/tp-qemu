import logging
import time

from autotest.client.shared import error, utils

from virttest import utils_misc
from virttest import utils_net
from virttest import env_process


@error.context_aware
def run(test, params, env):
    """
    Test qmp event notification function:
    1) Boot up guest with qmp and macvtap.
    2) In guest, change network interface to promisc state.
    3) Try to catch qmp event notification in qmp monitor.
    4) Execute query-rx-filter in host qmp session.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """

    qemu_binary = utils_misc.get_qemu_binary(params)
    if not utils_misc.qemu_has_option("qmp", qemu_binary):
        error.TestNAError("This test case requires a host QEMU with QMP "
                          "monitor support")
    if params.get("nettype", "macvtap") != "macvtap":
        error.TestNAError("This test case test macvtap.")

    params["start_vm"] = "yes"
    vm_name = params.get("main_vm", "vm1")
    env_process.preprocess_vm(test, params, env, vm_name)

    vm = env.get_vm(vm_name)
    vm.verify_alive()

    event_cmd = params.get("event_cmd")
    event_cmd_type = params.get("event_cmd_type")
    event_check = params.get("event_check")
    timeout = int(params.get("check_timeout", 360))
    pre_cmd = params.get("pre_cmd")
    post_cmd = params.get("post_cmd")
    post_cmd_type = params.get("post_cmd_type")

    session = vm.wait_for_serial_login(timeout=int(params.get("login_timeout",
                                                              360)))

    callback = {"host_cmd": utils.system_output,
                "guest_cmd": session.get_command_output,
                "qmp_cmd": vm.get_monitors_by_type("qmp")[0].send_args_cmd}

    def send_cmd(cmd, cmd_type):
        if cmd_type in callback.keys():
            return callback[cmd_type](cmd)
        else:
            raise error.TestError("cmd_type is not supported")

    if pre_cmd:
        error.context("Run pre_cmd '%s'", logging.info)
        pre_cmd_type = params.get("pre_cmd_type", event_cmd_type)
        send_cmd(pre_cmd, pre_cmd_type)

    mac = vm.get_mac_address()
    interface_name = utils_net.get_linux_ifname(session, mac)

    error.context("In guest, change network interface to promisc state.",
                  logging.info)
    event_cmd = params.get("event_cmd") % interface_name
    send_cmd(event_cmd, event_cmd_type)

    error.context("Try to get qmp events in %s seconds!" % timeout,
                  logging.info)
    end_time = time.time() + timeout
    qmp_monitors = vm.get_monitors_by_type("qmp")
    qmp_num = len(qmp_monitors)
    while time.time() < end_time:
        for monitor in qmp_monitors:
            event = monitor.get_event(event_check)
            if event:
                txt = "Monitr %s " % monitor.name
                txt += "receive qmp %s event notification" % event_check
                logging.info(txt)
                qmp_num -= 1
                qmp_monitors.remove(monitor)
        time.sleep(5)
        if qmp_num <= 0:
            break
    if qmp_num > 0:
        output = session.cmd("ip link show")
        err = "Monitor(s) "
        for monitor in qmp_monitors:
            err += "%s " % monitor.name
        err += " did not receive qmp %s event notification." % event_check
        err += " ip link show command output in guest: %s" % output
        raise error.TestFail(err)

    if post_cmd:
        for nic in vm.virtnet:
            post_cmd = post_cmd % nic.device_id
            error.context("Run post_cmd '%s'" % post_cmd, logging.info)
            post_cmd_type = params.get("post_cmd_type", event_cmd_type)
            output = send_cmd(post_cmd, post_cmd_type)
            post_cmd_check = params.get("post_cmd_check")
            if post_cmd_check:
                if post_cmd_check not in str(output):
                    err = "Did not find '%s' in " % post_cmd_check
                    err += "'%s' command's output: %s" % (post_cmd, output)
                    raise error.TestFail(err)

    if session:
        session.close()
