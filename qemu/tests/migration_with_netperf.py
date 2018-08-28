import logging

from virttest import error_context
from virttest import utils_netperf
from virttest import utils_misc
from virttest import data_dir
from virttest import utils_net


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
    netperf_link = utils_misc.get_path(data_dir.get_deps_dir("netperf"),
                                       params.get("netperf_link"))
    md5sum = params.get("pkg_md5sum")
    netperf_server_link = params.get("netperf_server_link_win")
    if netperf_server_link:
        netperf_server_link = utils_misc.get_path(data_dir.get_deps_dir("netperf"),
                                                  netperf_server_link)
    server_md5sum_win = params.get("server_md5sum")
    netperf_client_link = params.get("netperf_client_link_win", netperf_link)
    client_md5sum_win = params.get("client_md5sum", md5sum)
    netperf_client_link = utils_misc.get_path(data_dir.get_deps_dir("netperf"),
                                              netperf_client_link)
    server_path = params.get("server_path", "/var/tmp/")
    client_path = params.get("client_path", "/var/tmp/")
    server_path_win = params.get("server_path_win")
    client_path_win = params.get("client_path_win")

    username = params.get("username", "root")
    password = params.get("password", "redhat")
    passwd = params.get("hostpassword", "redhat")
    client = params.get("shell_client", "ssh")
    port = params.get("shell_port", "22")
    prompt = params.get("shell_prompt", r"^root@.*[\#\$]\s*$|#")
    linesep = params.get(
        "shell_linesep", "\n").encode().decode('unicode_escape')
    status_test_command = params.get("status_test_command", "echo $?")
    compile_option_client_h = params.get("compile_option_client_h", "")
    compile_option_server_h = params.get("compile_option_server_h", "")
    compile_option_client_g = params.get("compile_option_client_g", "")
    compile_option_server_g = params.get("compile_option_server_g", "")
    if params.get("os_type") == "linux":
        session.cmd("iptables -F", ignore_all_errors=True)
        g_client_link = netperf_link
        g_server_link = netperf_link
        g_server_path = server_path
        g_client_path = client_path
        g_server_md5sum = md5sum
        g_client_md5sum = md5sum
    elif params.get("os_type") == "windows":
        g_client_link = netperf_client_link
        g_server_link = netperf_server_link
        g_server_path = server_path_win
        g_client_path = client_path_win
        g_server_md5sum = server_md5sum_win
        g_client_md5sum = client_md5sum_win
    netperf_client_g = None
    netperf_client_h = None
    netperf_server_g = None
    netperf_server_h = None
    try:
        netperf_client_g = utils_netperf.NetperfClient(guest_address,
                                                       g_client_path,
                                                       g_client_md5sum,
                                                       g_client_link,
                                                       client=client,
                                                       port=port,
                                                       username=username,
                                                       password=password,
                                                       prompt=prompt,
                                                       linesep=linesep,
                                                       status_test_command=status_test_command,
                                                       compile_option=compile_option_client_g)
        netperf_server_h = utils_netperf.NetperfServer(remote_ip,
                                                       server_path,
                                                       md5sum,
                                                       netperf_link,
                                                       password=passwd,
                                                       prompt=prompt,
                                                       linesep=linesep,
                                                       status_test_command=status_test_command,
                                                       install=False,
                                                       compile_option=compile_option_server_h)
        netperf_client_h = utils_netperf.NetperfClient(remote_ip, client_path,
                                                       md5sum, netperf_link,
                                                       password=passwd,
                                                       prompt=prompt,
                                                       linesep=linesep,
                                                       status_test_command=status_test_command,
                                                       compile_option=compile_option_client_h)
        netperf_server_g = utils_netperf.NetperfServer(guest_address,
                                                       g_server_path,
                                                       g_server_md5sum,
                                                       g_server_link,
                                                       client=client,
                                                       port=port,
                                                       username=username,
                                                       password=password,
                                                       prompt=prompt,
                                                       linesep=linesep,
                                                       status_test_command=status_test_command,
                                                       compile_option=compile_option_server_g)
        error_context.base_context("Run netperf test between host and guest")
        error_context.context("Start netserver in guest.", logging.info)
        netperf_server_g.start()
        if netperf_server_h:
            error_context.context("Start netserver in host.", logging.info)
            netperf_server_h.start()

        error_context.context("Start Netperf in host", logging.info)
        test_option = "-l %s" % netperf_timeout
        netperf_client_h.bg_start(guest_address, test_option, client_num)
        if netperf_client_g:
            error_context.context("Start Netperf in guest", logging.info)
            netperf_client_g.bg_start(host_address, test_option, client_num)

        m_count = 0
        while netperf_client_h.is_netperf_running():
            m_count += 1
            error_context.context("Start migration iterations: %s " % m_count,
                                  logging.info)
            vm.migrate(mig_timeout, mig_protocol, mig_cancel_delay, env=env)
    finally:
        if netperf_server_g:
            if netperf_server_g.is_server_running():
                netperf_server_g.stop()
            netperf_server_g.package.env_cleanup(True)
        if netperf_server_h:
            if netperf_server_h.is_server_running():
                netperf_server_h.stop()
            netperf_server_h.package.env_cleanup(True)
        if netperf_client_h:
            if netperf_client_h.is_netperf_running():
                netperf_client_h.stop()
            netperf_client_h.package.env_cleanup(True)
        if netperf_client_g:
            if netperf_client_g.is_netperf_running():
                netperf_client_g.stop()
            netperf_client_g.package.env_cleanup(True)
        if session:
            session.close()
