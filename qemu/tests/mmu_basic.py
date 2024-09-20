import re

from virttest import error_context, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Test to disabling radix MMU mode on guest.
    Steps:
    1) There are two options, boot up a native(radix)guest or HPT guest.
    2) Check the MMU mode in the guest.
    3) Adding disable radix to guest's kernel line directly then reboot guest.
    4) Check again the MMU mode in the guest.
    5) Check guest call trace in dmesg log.


    :params test: QEMU test object.
    :params params: Dictionary with the test parameters.
    :params env: Dictionary with test environment.
    """

    def cpu_info_match(pattern):
        match = re.search(pattern, session.cmd_output("cat /proc/cpuinfo"))
        return True if match else False

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    error_context.context("Check the MMU mode.", test.log.info)
    if cpu_info_match("MMU"):
        if cpu_info_match("POWER9"):
            if cpu_info_match("Radix") is False:
                test.fail("mmu mode is not Radix, doesn't meet expectations.")
        else:
            if cpu_info_match("Hash") is False:
                test.fail("mmu mode is not Hash, doesn't meet expectations.")
    else:
        if params["mmu_option"] == "yes":
            test.fail("There should be MMU mode.")
    utils_test.update_boot_option(vm, args_added="disable_radix")
    session = vm.wait_for_login()

    error_context.context("Check the MMU mode.", test.log.info)
    if cpu_info_match("MMU"):
        if cpu_info_match("Hash") is False:
            test.fail("mmu mode is not Hash, mmu mode disabled failure.")
    else:
        if params["mmu_option"] == "yes":
            test.fail("There should be MMU mode.")

    vm.verify_dmesg()
