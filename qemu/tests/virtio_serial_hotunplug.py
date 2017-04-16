import re
import time
import logging
from autotest.client import utils
from autotest.client.shared import error
from virttest import utils_misc, utils_test


@error.context_aware
def run(test, params, env):
    """
    Test hot unplug virtio serial devices.

    1) Start guest with virtio serial device(s).
    2) Transfer data from guest to host through virtio serial device.
    3) Hot-unplug virtio serial port used in step 2 during test 2.
    4) Repeat step 2 and 3. (optional)
    4) Do migration test. (optional)

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def hotunplug(device, unplug_cmd="device_del", ignore_failure=False,
                  timeout=150):
        def _device_removed():
            after_del = vm.monitor.info("qtree")
            return device not in after_del

        cmd = "%s id=%s" % (unplug_cmd, device)
        vm.monitor.send_args_cmd(cmd)
        if (not utils_misc.wait_for(_device_removed, timeout, 5, 3) and
                not ignore_failure):
            msg = "Failed to hot remove device: %s. " % device
            msg += "Monitor command: %s" % cmd
            raise error.TestFail(msg)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    unplug_timeout = int(params.get("unplug_timeout", 150))

    unplug_devices = params["unplug_device"].split()
    bg_stress_run_flag = params.get("bg_stress_run_flag")

    qtree_output = vm.monitor.info("qtree")

    module = params.get("modprobe_module")
    if module:
        error.context("modprobe the module %s" % module, logging.info)
        session.cmd("modprobe %s" % module)

    context_msg = "Running sub test '%s' %s"
    sub_type = params.get("sub_type_before_unplug")
    if sub_type:
        error.context(context_msg % (sub_type, "before unplug"),
                      logging.info)
        utils_test.run_virt_sub_test(test, params, env, sub_type)

    for device in unplug_devices:
        sub_params = params.object_params(device)
        match_string = sub_params.get("match_string", "dev: %s, id \"(.*)\"")
        unplug_chardev = sub_params.get("unplug_chardev", "no") == "yes"
        device_type = sub_params.get("device_type")
        match_string = match_string % (device_type, device)
        try:
            device_id, chardev_id = re.findall(match_string, qtree_output)[0]
        except Exception, err:
            txt = "Fail to get device id from info qtree command. "
            txt += "match string: %s Error message: %s" % (match_string, err)
            txt += "info qtree output:\n%s" % qtree_output
            raise error.TestError(txt)
        error.context("Do file transfer between host and guest", logging.info)
        try:
            t_thread = None
            sender = params.get("file_sender", "both")
            md5_check = params.get("md5_check", "no") == "yes"
            runner = utils_test.run_virtio_serial_file_transfer
            t_thread = utils.InterruptedThread(runner,
                                               (test, params, env, device,
                                                sender, md5_check))
            t_thread.start()
            if bg_stress_run_flag:
                utils_misc.wait_for(lambda: env.get(bg_stress_run_flag),
                                    20, 0, 1,
                                    "Wait background file transfer start")
            error.context("Hot unplug device %s" % device, logging.info)
            if unplug_chardev:
                hotunplug(chardev_id, unplug_cmd="chardev-remove",
                          timeout=unplug_timeout)
            else:
                hotunplug(device_id)
        finally:
            if t_thread:
                output = t_thread.join(suppress_exception=True)
                logging.debug("File transfer thread output:\n%s", output)

    sub_type = params.get("sub_type_after_unplug")
    if sub_type:
        error.context(context_msg % (sub_type, "after hotunplug"),
                      logging.info)
        if sub_type == "migration":
            vm.params.pop("virtio_ports")
        utils_test.run_virt_sub_test(test, params, env, sub_type)
