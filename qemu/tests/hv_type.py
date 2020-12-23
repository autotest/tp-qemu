import logging

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Check the Hyper-V type

    1) boot the guest with all flags
    2) check Hyper-V type in guest

    param test: the test object
    param params: the test params
    param env: the test env object
    """
    timeout = params.get_numeric("timeout", 360)

    error_context.context("Boot the guest with all flags", logging.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    hv_type = session.cmd("virt-what")
    logging.debug("Guest 'virt-what': %s", hv_type)
    if "kvm" not in hv_type or "hyperv" not in hv_type:
        test.fail("Hyiper-V type mismatch, should be both KVM & hyperv")
