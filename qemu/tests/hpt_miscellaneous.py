import logging
import re

from virttest import error_context, utils_misc
from virttest.utils_test.qemu import MemoryHotplugTest

LOG_JOB = logging.getLogger("avocado.test")


def set_hpt(session, params, test, hpt_size):
    """Run this step to set HPT in guest"""
    set_cmd = "echo %s > /sys/kernel/debug/powerpc/hpt_order"
    st, o = session.cmd_status_output(set_cmd % (hpt_size))
    # Get output after set command,some errors are there but
    # they are acceptable
    if st:
        # Invalid parameters,hpt_size < 18 and hpt_size > 46
        if hpt_size < 18 or hpt_size > 46:
            if re.search(r"Invalid argument", o):
                return
        # Invalid parameter 0,it is handled in different way
        # by kernel so dealing with it particularly
        elif hpt_size == 0:
            if re.search(r"Input/output error", o):
                return
        else:
            test.fail("Set hpt test failed,please check:'%s'" % o)


def verify_hpt(test, params, session, hpt_size):
    """Run this step to check HPT in guest"""
    get_cmd = "cat /sys/kernel/debug/powerpc/hpt_order"
    if params.get("sub_type") != "negative":
        s, get_hpt_value = session.cmd_status_output(get_cmd)
        if s:
            test.fail("Fail to get HPT value")
        else:
            if int(get_hpt_value) != hpt_size:
                test.fail(
                    "HPT order not match! '%s' vs '%s'" % (get_hpt_value, hpt_size)
                )


def check_mem_increase(session, params, orig_mem, increase_mem):
    """Check the size of memory increased."""
    new_mem = int(session.cmd_output(cmd=params["free_mem_cmd"]))
    if (new_mem - orig_mem) == increase_mem:
        error_context.context(
            "Get guest free memory size after hotplug pc-dimm.", LOG_JOB.info
        )
        LOG_JOB.debug("Guest free memory size is %d bytes", new_mem)
        LOG_JOB.info("Guest memory size is increased %s.", params["expected_size"])
        return True
    return False


@error_context.context_aware
def run(test, params, env):
    """
    QEMU HPT miscellaneous test:
    Scenario 1
    1) Start a HPT guest on Power8 or Power9 host
    2) Increase HPT
    3) Reboot

    Scenario 2
    1) Start a HPT guest on Power8 or Power9 host
    2) Reduce HPT
    3) Reboot

    Scenario 3
    1) Hotplug 1G memory to the guest
    2) Increase HPT
    3) Decrease HPT

    Scenario 4
    1) Start a HPT guest on Power8 and Power9 host
    2) Resize hpt consectively with different params
    3) Check guest work well or not

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("Start miscellaneous HPT test...", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    check_exist_cmd = "ls /sys/kernel/debug/powerpc/hpt_order"
    status = session.cmd_status(check_exist_cmd)
    if status:
        test.cancel("The guest doesn't support hpt resize so skip test")
    check_def_cmd = "cat /sys/kernel/debug/powerpc/hpt_order"
    st, get_hpt_def = session.cmd_status_output(check_def_cmd)
    if st:
        test.fail("Fail to get HPT value")
    hpt_size = int(get_hpt_def)
    hpt_default = int(get_hpt_def)
    test.log.debug("Default hpt order : '%s'", get_hpt_def)
    increment_sequence = params.get("increment_sequence").split()
    error_context.context("hpt changes according to increment", test.log.info)
    if params.get("sub_type") == "mem":
        # For HPT reszing after hotplug memory
        orig_mem = int(session.cmd_output(cmd=params["free_mem_cmd"]))
        hpt_mem = MemoryHotplugTest(test, params, env)
        hpt_mem.hotplug_memory(vm, params["plug_mem_name"])
        increase_mem = int(params["expected_size"])
        test.log.debug("Guest free memory size is %d bytes", orig_mem)
        plug_timeout = float(params.get("plug_timeout", 20))
        if not utils_misc.wait_for(
            lambda: check_mem_increase(session, params, orig_mem, increase_mem),
            plug_timeout,
        ):
            test.fail(
                "Guest memory size is not increased %s in %s sec."
                % (increase_mem, plug_timeout)
            )
    for increm in increment_sequence:
        hpt_size = hpt_size + int(increm)
        set_hpt(session, params, test, hpt_size)
        verify_hpt(test, params, session, hpt_size)
    if "reboot" in params.get("sub_type"):
        session = vm.reboot(session)
        vm.verify_alive()
        verify_hpt(test, params, session, hpt_default)
    if params.get("sub_type") == "migration":
        # do migration
        mig_timeout = params.get_numeric("mig_timeout", "3600", float)
        mig_protocol = params.get("migration_protocol", "tcp")
        vm.migrate(mig_timeout, mig_protocol, env=env)
        session = vm.wait_for_login()
        verify_hpt(test, params, session, hpt_size)
    vm.verify_kernel_crash()
