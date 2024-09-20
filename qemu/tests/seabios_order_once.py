import os
import re

from avocado.utils import process
from virttest import env_process, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    KVM Seabios test:
    [seabios]Boot guest with "-boot order/once" option
    1) Start VM with sga bios
    2) Check boot order before reboot
    3) Reboot the VM
    4) Check boot order after reboot

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def create_cdroms(cdrom_test):
        """
        Create 'test' cdrom with one file on it
        """
        test.log.info("creating test cdrom")
        process.run("dd if=/dev/urandom of=test bs=10M count=1")
        process.run("mkisofs -o %s test" % cdrom_test)
        process.run("rm -f test")

    def cleanup_cdroms(cdrom_test):
        """
        Removes created cdrom
        """
        test.log.info("cleaning up temp cdrom images")
        os.remove(cdrom_test)

    def boot_check(info):
        """
        boot info check
        """
        if params["enable_sga"] == "yes":
            output = vm.serial_console.get_stripped_output()
        else:
            output = vm.serial_console.get_output()
        return re.search(info, output, re.S)

    cdrom_test = params["cdrom_test"]
    create_cdroms(cdrom_test)
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))

    error_context.context("Start VM with sga bios", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    vm.pause()
    # Disable nic device, boot fail from nic device except user model
    if params["nettype"] != "user":
        for nic in vm.virtnet:
            vm.set_link(nic.device_id, up=False)
    vm.resume()

    timeout = int(params.get("boot_timeout", 90))
    restart_key = params["restart_key"]
    boot_info1 = params["boot_info1"]
    boot_info2 = params["boot_info2"]
    bootorder_before = params["bootorder_before"]
    bootorder_after = params["bootorder_after"]

    try:
        error_context.context("Check boot order before reboot", test.log.info)
        if not utils_misc.wait_for(lambda: boot_check(boot_info1), timeout, 1):
            test.fail(
                "Guest isn't booted as expected order before reboot: %s"
                % bootorder_before
            )

        error_context.context("Reboot", test.log.info)
        vm.send_key(restart_key)

        error_context.context("Check boot order after reboot", test.log.info)
        boot_info = boot_info1 + boot_info2
        if not utils_misc.wait_for(lambda: boot_check(boot_info), timeout, 1):
            test.fail(
                "Guest isn't booted as expected order after reboot: %s"
                % bootorder_after
            )
    finally:
        cleanup_cdroms(cdrom_test)
