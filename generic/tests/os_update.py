def run(test, params, env):
    """
    Runs yum update and yum update kernel on RHEL or apt
    update and apt upgrade on Ubuntu based multi VM environment.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vms = env.get_all_vms()
    timeout = int(params.get("os_update_timeout"))
    for vm in vms:
        if not vm.is_alive():
            vm.start()
        cmd = "yum update -y"
        if "ubuntu" in vm.get_distro().lower():
            cmd = "apt update && apt upgrade -y"
        session = vm.wait_for_login()
        test.log.debug("Performing %s on VM %s", cmd, vm.name)
        if session.cmd_status(cmd, timeout=timeout) != 0:
            test.fail("Failed to update VM %s using %s" % (vm.name, cmd))
        session.close()
