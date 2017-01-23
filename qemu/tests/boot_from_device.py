import os
import re
import time
import logging

from autotest.client import utils
from autotest.client.shared import error

from virttest import utils_misc
from virttest import data_dir
from virttest import qemu_storage
from virttest import env_process


@error.context_aware
def run(test, params, env):
    """
    QEMU boot from device:

    1) Start guest from device(hd/usb/scsi-hd)
    2) Check the boot result
    3) Log into the guest if it's up
    4) Shutdown the guest if it's up

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def create_cdroms():
        """
        Create 'test' cdrom with one file on it
        """

        logging.info("creating test cdrom")
        cdrom_test = params.get("cdrom_test")
        cdrom_test = utils_misc.get_path(data_dir.get_data_dir(), cdrom_test)
        utils.run("dd if=/dev/urandom of=test bs=10M count=1")
        utils.run("mkisofs -o %s test" % cdrom_test)
        utils.run("rm -f test")

    def cleanup_cdroms():
        """
        Removes created cdrom
        """

        logging.info("cleaning up temp cdrom images")
        cdrom_test = utils_misc.get_path(
            data_dir.get_data_dir(), params.get("cdrom_test"))
        os.remove(cdrom_test)

    def preprocess_remote_storage():
        """
        Prepare remote ISCSI storage for block image, and login session for
        iscsi device.
        """
        image_name = params.get("images").split()[0]
        base_dir = params.get("images_base_dir", data_dir.get_data_dir())
        iscsidevice = qemu_storage.Iscsidev(params, base_dir, image_name)
        iscsidevice.setup()

    def postprocess_remote_storage():
        """
        Logout from target.
        """
        image_name = params.get("images").split()[0]
        base_dir = params.get("images_base_dir", data_dir.get_data_dir())
        iscsidevice = qemu_storage.Iscsidev(params, base_dir, image_name)
        iscsidevice.cleanup()

    def cleanup(dev_name):
        if dev_name == "scsi-cd":
            cleanup_cdroms()
        elif dev_name == "iscsi-dev":
            postprocess_remote_storage()

    def check_boot_result(boot_fail_info, device_name):
        """
        Check boot result, and logout from iscsi device if boot from iscsi.
        """

        logging.info("Wait for display and check boot info.")
        infos = boot_fail_info.split(';')
        start = time.time()
        while True:
            console_str = vm.serial_console.get_stripped_output()
            match = re.search(infos[0], console_str)
            if match or time.time() > start + timeout:
                break
            time.sleep(1)
        logging.info("Try to boot from '%s'" % device_name)
        try:
            if dev_name == "hard-drive" or (dev_name == "scsi-hd" and not
                                            params.get("image_name_stg")):
                error.context("Log into the guest to verify it's up",
                              logging.info)
                session = vm.wait_for_login(timeout=timeout)
                session.close()
                vm.destroy()
                return

            output = vm.serial_console.get_stripped_output()

            for i in infos:
                if not re.search(i, output):
                    raise error.TestFail("Could not boot from"
                                         " '%s'" % device_name)
        finally:
            cleanup(device_name)

    timeout = int(params.get("login_timeout", 360))
    boot_menu_key = 'esc '
    boot_menu_hint = params.get("boot_menu_hint")
    boot_fail_info = params.get("boot_fail_info")
    boot_device = params.get("boot_device")
    dev_name = params.get("dev_name")
    if dev_name == "scsi-cd":
        create_cdroms()
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params.get("main_vm"))
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
    elif dev_name == "iscsi-dev":
        preprocess_remote_storage()
        params["start_vm"] = "yes"
        env_process.preprocess_vm(test, params, env, params.get("main_vm"))
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
    else:
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
    if boot_device:
        match = False
        start = time.time()
        while True:
            console_str = vm.serial_console.get_stripped_output()
            match = re.search(boot_menu_hint, console_str)
            if match or time.time() > start + timeout:
                break
            time.sleep(1)
        if not match:
            cleanup(dev_name)
            raise error.TestFail("Could not get boot menu message. "
                                 "Excepted Result: '%s', Actual result: '%s'"
                                 % (boot_menu_hint, console_str))

        # Send boot menu key in monitor.
        vm.send_key(boot_menu_key)

        output = vm.serial_console.get_stripped_output()
        boot_list = re.findall("^\d+\. (.*)\s", output, re.M)

        if not boot_list:
            cleanup(dev_name)
            raise error.TestFail("Could not get boot entries list.")

        logging.info("Got boot menu entries: '%s'", boot_list)
        for i, v in enumerate(boot_list, start=1):
            if re.search(boot_device, v, re.I):
                logging.info("Start guest from boot entry '%s'" % boot_device)
                vm.send_key(str(i))
                break
        else:
            raise error.TestFail("Could not get any boot entry match "
                                 "pattern '%s'" % boot_device)

    check_boot_result(boot_fail_info, dev_name)
