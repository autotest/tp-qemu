from virttest import env_process, error_context, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Boot guest without vectors, then do file transfer/ping test

    1) Boot up VM without vectors
    2) Do ping test(do not need this step for vhostforce tests)
    3) Check guest pci msi support
    4) Do file transfer test
    5) Disable pci msi and do 2-4 again
    6) If vhostforce is set, repeat 3-4

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    def check_msi_support(session):
        """
        Check MSI support in guest

        :param session: guest session
        """
        if params["os_type"] == "linux":
            devices = session.cmd_output("lspci | grep Eth").strip()
            error_context.context(
                "Check if vnic inside guest support msi.", test.log.info
            )
            for device in devices.splitlines():
                if not device:
                    continue
                d_id = device.split()[0]
                msi_check_cmd = params["msi_check_cmd"] % d_id
                output = session.cmd_output(msi_check_cmd)
                if output:
                    req_args = utils_test.check_kernel_cmdline(
                        session, args="pci=nomsi"
                    )
                    if not req_args:
                        if "MSI-X: Enable-" in output:
                            test.log.info("MSI-X is disabled")
                        else:
                            msg = "Command %s get wrong" % msi_check_cmd
                            msg += " output when no vectors in qemu cmd"
                            msg += " line and nomsi in /proc/cmdline"
                            test.fail(msg)

    def do_test(test, params, env):
        """
        Do ping test, check msi support and do file transfer

        :param session: guest session
        :param vm: guest vm
        """
        login_timeout = int(params.get("login_timeout", 360))
        env_process.preprocess(test, params, env)
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        session = vm.wait_for_login(timeout=login_timeout)
        guest_ip = vm.get_address()
        ping_count = int(params.get("ping_count", 0))
        if not ping_count == 0:
            status, output = utils_test.ping(
                guest_ip, ping_count, timeout=float(ping_count) * 1.5
            )
            if status != 0:
                test.fail("Ping returns non-zero value %s" % output)

            package_lost = utils_test.get_loss_ratio(output)
            if package_lost != 0:
                test.fail("%s packeage lost when ping server" % package_lost)

        check_msi_support(session)

        if params.get("do_file_transfer", "no") == "yes":
            utils_test.run_file_transfer(test, params, env)

        session.close()
        vm.destroy(gracefully=True)

    # enable pci msi and do test
    params["start_vm"] = "yes"
    params["enable_msix_vectors"] = "no"
    do_test(test, params, env)

    # disable pci msi and do test
    params["disable_pci_msi"] = "yes"
    do_test(test, params, env)
