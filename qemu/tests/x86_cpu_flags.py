import logging

from avocado.utils import cpu
from virttest import error_context, env_process
from qemu.tests.x86_cpu_model import check_flags


@error_context.context_aware
def run(test, params, env):
    """
    Test cpu flags.
    1) Check if current flags are in the supported lists, if no, cancel test
    2) Otherwise, boot guest with the cpu flags
    3) Check cpu flags inside guest(only for linux guest)
    4) Reboot guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vendor_id = params.get("vendor_id", "")
    if vendor_id:
        if vendor_id != cpu.get_vendor():
            test.cancel("Need host vendor %s to support this test case" % vendor_id)

    flags = params["flags"]
    check_host_flags = params.get_boolean("check_host_flags")
    if check_host_flags:
        check_flags(params, flags, test)

    params["start_vm"] = "yes"
    vm_name = params['main_vm']
    env_process.preprocess_vm(test, params, env, vm_name)

    vm = env.get_vm(vm_name)
    error_context.context("Try to log into guest", logging.info)
    session = vm.wait_for_login()
    if params["os_type"] == "linux":
        check_flags(params, flags, test, session)

    if params.get("reboot_method"):
        error_context.context("Reboot guest '%s'." % vm.name, logging.info)
        session = vm.reboot(session=session)

    vm.verify_kernel_crash()
    session.close()
