from virttest import error_context, utils_sriov


@error_context.context_aware
def run(test, params, env):
    """
    iGB VFs shutdown test:
    1) Log into a guest
    2) create max number vfs for PF
    3) shutdown guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    timeout = float(params.get("login_timeout", 240))
    shutdown_command = params.get("shutdown_command")
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login(timeout=timeout)
    error_context.context("Create emulate VFs devices", test.log.info)
    pci_id = params.get("get_pci_id")
    nic_pci = session.cmd_output(pci_id).strip()
    check_vf_num = params.get("get_vf_num")
    sriov_numvfs = int(session.cmd_output(check_vf_num % nic_pci))
    utils_sriov.set_vf(
        f"/sys/bus/pci/devices/{nic_pci}", vf_no=sriov_numvfs, session=session
    )
    session.sendline(shutdown_command)
    error_context.context("waiting VM to go down (shutdown shell cmd)", test.log.info)
    if not vm.wait_for_shutdown(360):
        test.fail("Guest refuses to go down")
    session.close()
