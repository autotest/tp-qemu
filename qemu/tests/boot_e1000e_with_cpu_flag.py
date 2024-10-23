from virttest import error_context, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Boot a winodws guest add Vendor ID with name "KVMKVMKVM" to cpu model flag

    1) Boot a vm with 'e1000e + hv_vendor_id=KVMKVMKVM' on q35 machine
    2) Run the bcdedit command as administrator
    3) reboot guest by shell
    4) do ping test

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    login_timeout = params.get_numeric("login_timeout", 360)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session_serial = vm.wait_for_serial_login(timeout=login_timeout)
    bcdedit_debug = params["bcdedit_debug"]
    bcdedit_cmd = params["bcdedit_cmd"]
    ext_host = utils_net.get_default_gateway()

    try:
        session_serial.cmd(bcdedit_debug)
        session_serial.cmd(bcdedit_cmd)
        vm.reboot(timeout=login_timeout)
        status, output = utils_net.ping(
            dest=ext_host, count=10, session=session_serial, timeout=30
        )
        if status:
            test.fail("ping is failed, output %s" % output)
    finally:
        session_serial.close()
