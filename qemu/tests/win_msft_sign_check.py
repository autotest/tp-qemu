from virttest import error_context, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    sigverif test:
    1) Boot guest with related virtio devices
    2) Run driver signature check command in guest

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    driver_name = params["driver_name"]
    driver_verifier = params.get("driver_verifier", driver_name)
    session = utils_test.qemu.windrv_check_running_verifier(
        session, vm, test, driver_verifier
    )

    # check if Windows VirtIO driver is msft digital signed.
    device_name = params["device_name"]
    chk_cmd = params["vio_driver_chk_cmd"] % device_name[0:30]
    chk_timeout = int(params.get("chk_timeout", 240))
    error_context.context("%s Driver Check" % driver_name, test.log.info)
    chk_output = session.cmd_output(chk_cmd, timeout=chk_timeout)
    if "FALSE" in chk_output:
        fail_log = "VirtIO driver is not digitally signed!"
        fail_log += "    VirtIO driver check output: '%s'" % chk_output
        test.fail(fail_log)
    elif "TRUE" in chk_output:
        pass
    else:
        test.error("Device %s is not found in guest" % device_name)
