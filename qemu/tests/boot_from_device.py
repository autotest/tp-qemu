import os
import re

from avocado.utils import process
from virttest import env_process, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    QEMU boot from device:
    1) Start guest from device
       ide-hd/virtio-blk/scsi-hd/usb-storage
       ide-cd/scsi-cd
    2) Check the boot result

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
        return re.search(info, get_serial_console_output(), re.S)

    def get_serial_console_output():
        """
        get the output of serail console
        """
        if params["enable_sga"] == "yes":
            output = vm.serial_console.get_stripped_output()
        else:
            output = vm.serial_console.get_output()
        return output

    timeout = int(params.get("login_timeout", 360))
    boot_menu_key = params.get("boot_menu_key", "esc")
    boot_menu_hint = params["boot_menu_hint"]
    boot_entry_info = params["boot_entry_info"]
    boot_dev = params.get("boot_dev")
    dev_name = params.get("dev_name")

    if dev_name == "cdrom":
        cdrom_test = params["cdrom_test"]
        create_cdroms(cdrom_test)
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params.get("main_vm"))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    try:
        if boot_dev:
            if not utils_misc.wait_for(lambda: boot_check(boot_menu_hint), timeout, 1):
                test.fail("Could not get boot menu message")

            # Send boot menu key in monitor.
            vm.send_key(boot_menu_key)

            output = get_serial_console_output()
            boot_list = re.findall(r"^\d+\. (.*)\s", output, re.M)
            if not boot_list:
                test.fail("Could not get boot entries list")
            test.log.info("Got boot menu entries: '%s'", boot_list)

            for i, v in enumerate(boot_list, start=1):
                if re.search(boot_dev, v, re.I):
                    msg = "Start guest from boot entry '%s'" % boot_dev
                    error_context.context(msg, test.log.info)
                    vm.send_key(str(i))
                    break
            else:
                msg = "Could not get boot entry match pattern '%s'" % boot_dev
                test.fail(msg)

        error_context.context("Check boot result", test.log.info)
        if not utils_misc.wait_for(lambda: boot_check(boot_entry_info), timeout, 1):
            test.fail("Could not boot from '%s'" % dev_name)
    finally:
        if dev_name == "cdrom":
            cleanup_cdroms(cdrom_test)
