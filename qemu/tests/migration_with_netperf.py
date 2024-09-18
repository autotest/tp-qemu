import os

from virttest import data_dir, error_context, utils_net, utils_netperf


@error_context.context_aware
def run(test, params, env):
    """
    KVM migration test:
    1) Start a guest.
    2) Start netperf server in guest.
    3) Start multi netperf clients in host.
    4) Migrate the guest in local during netperf clients working.
    5) Repeatedly migrate VM and wait until netperf clients stopped.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    login_timeout = int(params.get("login_timeout", 360))
    mig_timeout = float(params.get("mig_timeout", "3600"))
    mig_protocol = params.get("migration_protocol", "tcp")
    mig_cancel_delay = int(params.get("mig_cancel") == "yes") * 2
    netperf_timeout = int(params.get("netperf_timeout", "300"))
    client_num = int(params.get("client_num", "100"))

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)
    guest_address = vm.get_address()
    host_address = utils_net.get_host_ip_address(params)
    remote_ip = params.get("remote_host", host_address)
    netperf_link = os.path.join(
        data_dir.get_deps_dir("netperf"), params.get("netperf_link")
    )
    netperf_server_link = params.get("netperf_server_link_win")
    if netperf_server_link:
        netperf_server_link = os.path.join(
            data_dir.get_deps_dir("netperf"), netperf_server_link
        )
    netperf_client_link = params.get("netperf_client_link_win", netperf_link)
    netperf_client_link = os.path.join(
        data_dir.get_deps_dir("netperf"), netperf_client_link
    )
    server_path = params.get("server_path", "/var/tmp/")
    client_path = params.get("client_path", "/var/tmp/")
    server_path_win = params.get("server_path_win")
    client_path_win = params.get("client_path_win")
    disable_firewall = params.get("disable_firewall", "")
    session.cmd(disable_firewall, ignore_all_errors=True)

    if params.get("os_type") == "linux":
        g_client_link = netperf_link
        g_server_link = netperf_link
        g_server_path = server_path
        g_client_path = client_path
    elif params.get("os_type") == "windows":
        g_client_link = netperf_client_link
        g_server_link = netperf_server_link
        g_server_path = server_path_win
        g_client_path = client_path_win
    else:
        raise ValueError(f"unsupported os type: {params.get('os_type')}")

    netperf_client_g = None
    netperf_client_h = None
    netperf_server_g = None
    netperf_server_h = None
    try:
        netperf_client_g = utils_netperf.NetperfClient(
            guest_address,
            g_client_path,
            netperf_source=g_client_link,
            client=params.get("shell_client"),
            port=params.get("shell_port"),
            prompt=params.get("shell_prompt", r"^root@.*[\#\$]\s*$|#"),
            username=params.get("username"),
            password=params.get("password"),
            linesep=params.get("shell_linesep", "\n").encode().decode("unicode_escape"),
            status_test_command=params.get("status_test_command", ""),
            compile_option=params.get("compile_option_client_g", ""),
        )
        netperf_server_h = utils_netperf.NetperfServer(
            remote_ip,
            server_path,
            netperf_source=netperf_link,
            password=params.get("hostpassword"),
            compile_option=params.get("compile_option", ""),
        )
        netperf_client_h = utils_netperf.NetperfClient(
            remote_ip,
            client_path,
            netperf_source=netperf_link,
            password=params.get("hostpassword"),
            compile_option=params.get("compile_option", ""),
        )
        netperf_server_g = utils_netperf.NetperfServer(
            guest_address,
            g_server_path,
            netperf_source=g_server_link,
            username=params.get("username"),
            password=params.get("password"),
            client=params.get("shell_client"),
            port=params.get("shell_port"),
            prompt=params.get("shell_prompt", r"^root@.*[\#\$]\s*$|#"),
            linesep=params.get("shell_linesep", "\n").encode().decode("unicode_escape"),
            status_test_command=params.get("status_test_command", "echo $?"),
            compile_option=params.get("compile_option_server_g", ""),
        )
        error_context.base_context("Run netperf test between host and guest")
        error_context.context("Start netserver in guest.", test.log.info)
        netperf_server_g.start()
        if netperf_server_h:
            error_context.context("Start netserver in host.", test.log.info)
            netperf_server_h.start()

        error_context.context("Start Netperf in host", test.log.info)
        test_option = "-l %s" % netperf_timeout
        netperf_client_h.bg_start(guest_address, test_option, client_num)
        if netperf_client_g:
            error_context.context("Start Netperf in guest", test.log.info)
            netperf_client_g.bg_start(host_address, test_option, client_num)

        m_count = 0
        while netperf_client_h.is_netperf_running():
            m_count += 1
            error_context.context(
                "Start migration iterations: %s " % m_count, test.log.info
            )
            vm.migrate(mig_timeout, mig_protocol, mig_cancel_delay, env=env)
    finally:
        if netperf_server_g:
            if netperf_server_g.is_server_running():
                netperf_server_g.stop()
            netperf_server_g.cleanup(True)
        if netperf_server_h:
            if netperf_server_h.is_server_running():
                netperf_server_h.stop()
            netperf_server_h.cleanup(True)
        if netperf_client_h:
            if netperf_client_h.is_netperf_running():
                netperf_client_h.stop()
            netperf_client_h.cleanup(True)
        if netperf_client_g:
            if netperf_client_g.is_netperf_running():
                netperf_client_g.stop()
            netperf_client_g.cleanup(True)
        if session:
            session.close()
