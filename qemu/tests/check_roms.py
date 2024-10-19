import re

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    QEMU check roms test:

    1) start VM with additional option ROMS
    2) run "info roms" in qemu monitor
    3) check the roms are loaded once not twice

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    error_context.context("start VM with additional option roms", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    fw_filter = params["fw_filter"]
    addr_filter = params["addr_filter"]

    error_context.context("run 'info roms' in qemu monitor", test.log.info)
    o = vm.monitor.info("roms")

    # list_fw means rom being loaded by firmware
    # list_addr means rom being loaded by QEMU itself
    list_fw = []
    list_addr = []

    patt = re.compile(r"%s" % fw_filter, re.M)
    list_fw = patt.findall(str(o))

    patt = re.compile(r"%s" % addr_filter, re.M)
    list_addr = patt.findall(str(o))

    test.log.info("ROMS reported by firmware: '%s'", list_fw)
    test.log.info("ROMS reported by QEMU: '%s'", list_addr)

    error_context.context("check result for the roms", test.log.info)
    ret = set(list_fw).intersection(list_addr)
    if ret:
        test.fail(
            "ROM '%s' is intended to be loaded by the firmware, "
            "but is was also loaded by QEMU itself." % ret
        )
