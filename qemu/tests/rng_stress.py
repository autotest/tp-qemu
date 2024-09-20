import re
import time

import aexpect
from avocado.utils import process
from virttest import error_context, utils_test
from virttest.qemu_devices import qdevices


@error_context.context_aware
def run(test, params, env):
    """
    1) Boot up vm with one or more rng devices
    2) Read from /dev/random in host (optional)
    3) Run random read in guest
    4) Switch rng device if there is more than on rng devices
    5) Run random read in guest
    6) Read from /dev/random in host (optional)
    7) Clean random read in host (optional)
    """

    def get_rng_list(vm):
        """
        Get attached rng devices from device dictionary
        """
        rng_list = []
        rng_driver = params["rng_driver"]
        for device in vm.devices:
            if isinstance(device, qdevices.QDevice):
                if device.get_param("driver") == rng_driver:
                    rng_list.append(device)
        return rng_list

    def get_available_rng(session):
        """
        Get available rng devices from /sys/devices
        """
        verify_cmd = params["driver_available_cmd"]
        driver_name = params["driver_name"]
        try:
            output = session.cmd_output_safe(verify_cmd)
            rng_devices = re.findall(r"%s(?:\.\d+)?" % driver_name, output)
        except aexpect.ShellTimeoutError:
            err = "%s timeout, pls check if it's a product bug" % verify_cmd
            test.fail(err)
        return rng_devices

    login_timeout = int(params.get("login_timeout", 360))
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)
    sub_test = params.get("sub_test")

    if params.get("pre_cmd"):
        error_context.context("Fetch data from host", test.log.info)
        process.system(params.get("pre_cmd"), shell=True, ignore_bg_processes=True)

    error_context.context("Read rng device in guest", test.log.info)
    utils_test.run_virt_sub_test(test, params, env, sub_test)

    if params.get("os_type") == "linux":
        error_context.context("Query virtio rng device in guest", test.log.info)
        rng_devices = get_available_rng(session)
        rng_attached = get_rng_list(vm)
        if len(rng_devices) != len(rng_attached):
            test.fail(
                "The devices get from rng_arriable"
                " don't match the rng devices attached"
            )

        if len(rng_devices) > 1:
            for rng_device in rng_devices:
                error_context.context(
                    "Change virtio rng device to %s" % rng_device, test.log.info
                )
                session.cmd_status(params.get("switch_rng_cmd") % rng_device)
                error_context.context(
                    "Read from %s in guest" % rng_device, test.log.info
                )
                utils_test.run_virt_sub_test(test, params, env, sub_test)

    if params.get("post_cmd"):
        end_time = time.time() + 20
        while time.time() < end_time:
            s = process.system(
                params.get("post_cmd"),
                ignore_status=(params.get("ignore_status") == "yes"),
                shell=True,
            )
            if s == 0:
                break
