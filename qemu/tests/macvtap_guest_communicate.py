import os

from virttest import data_dir, error_context, utils_misc, utils_net, utils_netperf


@error_context.context_aware
def run(test, params, env):
    """
    Test Step:
        1. Boot up two guest with vnic over macvtap, mode vepa, and vhost=on
        2. Ping from guest1 to guest2 for 30 counts
        3. Run netperf stress test between two guest
    Params:
        :param test: QEMU test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
    """

    def ping_test():
        # Ping from guest1 to guest2 for 30 counts
        status, output = utils_net.ping(
            dest=addresses[1], count=30, timeout=60, session=sessions[0]
        )
        if status:
            test.fail("ping %s unexpected, output %s" % (vms[1], output))

    def netperf_test():
        """
        Netperf stress test between two guest.
        """
        n_client = utils_netperf.NetperfClient(
            addresses[0],
            params["client_path"],
            netperf_source=os.path.join(
                data_dir.get_deps_dir("netperf"), params.get("netperf_client_link")
            ),
            client=params.get("shell_client"),
            port=params.get("shell_port"),
            prompt=params.get("shell_prompt", r"^root@.*[\#\$]\s*$|#"),
            username=params.get("username"),
            password=params.get("password"),
            linesep=params.get("shell_linesep", "\n").encode().decode("unicode_escape"),
            status_test_command=params.get("status_test_command", ""),
            compile_option=params.get("compile_option_client", ""),
        )

        n_server = utils_netperf.NetperfServer(
            addresses[1],
            params["server_path"],
            netperf_source=os.path.join(
                data_dir.get_deps_dir("netperf"), params.get("netperf_server_link")
            ),
            username=params.get("username"),
            password=params.get("password"),
            client=params.get("shell_client"),
            port=params.get("shell_port"),
            prompt=params.get("shell_prompt", r"^root@.*[\#\$]\s*$|#"),
            linesep=params.get("shell_linesep", "\n").encode().decode("unicode_escape"),
            status_test_command=params.get("status_test_command", "echo $?"),
            compile_option=params.get("compile_option_server", ""),
        )

        try:
            n_server.start()
            # Run netperf with message size defined in range.
            netperf_test_duration = params.get_numeric("netperf_test_duration")
            test_protocols = params.get("test_protocols", "TCP_STREAM")
            netperf_output_unit = params.get("netperf_output_unit")
            test_option = params.get("test_option", "")
            test_option += " -l %s" % netperf_test_duration
            if netperf_output_unit in "GMKgmk":
                test_option += " -f %s" % netperf_output_unit
            t_option = "%s -t %s" % (test_option, test_protocols)
            n_client.bg_start(
                addresses[1],
                t_option,
                params.get_numeric("netperf_para_sessions"),
                params.get("netperf_cmd_prefix", ""),
                package_sizes=params.get("netperf_sizes"),
            )
            if utils_misc.wait_for(
                n_client.is_netperf_running, 10, 0, 1, "Wait netperf test start"
            ):
                test.log.info("Netperf test start successfully.")
            else:
                test.error("Can not start netperf client.")
            utils_misc.wait_for(
                lambda: not n_client.is_netperf_running(),
                netperf_test_duration,
                0,
                5,
                "Wait netperf test finish %ss" % netperf_test_duration,
            )
        finally:
            n_server.stop()
            n_server.cleanup(True)
            n_client.cleanup(True)

    login_timeout = params.get_numeric("login_timeout", 360)
    sessions = []
    addresses = []
    vms = []
    error_context.context("Init boot the vms")
    for vm_name in params.objects("vms"):
        vm = env.get_vm(vm_name)
        vms.append(vm)
        vm.verify_alive()
        sessions.append(vm.wait_for_login(timeout=login_timeout))
        addresses.append(vm.get_address())

    try:
        ping_test()
        netperf_test()
    finally:
        for session in sessions:
            if session:
                session.close()
