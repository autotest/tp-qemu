import os
import re

from avocado.utils import process
from virttest import data_dir, env_process, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    KVM seabios test:
    1) Start guest with sga bios
    2) Check the boot result when '-boot strict=on/off'
       on:  Hard Disk -> NIC
       off: Hard Disk -> NIC -> DVD/CD ...

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def create_cdrom():
        """
        Create 'test' cdrom
        """
        test.log.info("creating test cdrom")
        cdrom_test = params.get("cdrom_test", "/tmp/test.iso")
        cdrom_test = utils_misc.get_path(data_dir.get_data_dir(), cdrom_test)
        process.run("dd if=/dev/urandom of=test bs=10M count=1")
        process.run("mkisofs -o %s test" % cdrom_test)
        process.run("rm -f test")

    def cleanup_cdrom():
        """
        Remove 'test' cdrom
        """
        test.log.info("cleaning up test cdrom")
        cdrom_test = utils_misc.get_path(
            data_dir.get_data_dir(), params.get("cdrom_test")
        )
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

    error_context.context("Start guest with sga bios", test.log.info)
    create_cdrom()
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params.get("main_vm"))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.pause()

    # Disable nic device, boot fail from nic device except user model
    if params["nettype"] != "user":
        for nic in vm.virtnet:
            process.system("ifconfig %s down" % nic.ifname)
    vm.resume()

    timeout = float(params.get("login_timeout", 240))
    fail_infos = params["boot_fail_infos"]
    fail_infos_ex = params["boot_fail_infos_extra"]
    boot_strict = params["boot_strict"] == "on"

    try:
        error_context.context("Check guest boot result", test.log.info)
        if not utils_misc.wait_for(lambda: boot_check(fail_infos), timeout, 1):
            err = "Guest does not boot from Hard Disk first and then NIC"
            test.fail(err)

        if utils_misc.wait_for(lambda: boot_check(fail_infos_ex), timeout, 1):
            if boot_strict:
                err = "Guest tries to boot from DVD/CD when 'strict' is on"
                test.fail(err)
        else:
            if not boot_strict:
                err = "Guest does not try to boot from DVD/CD"
                err += " when 'strict' is off"
                test.fail(err)
    finally:
        cleanup_cdrom()
