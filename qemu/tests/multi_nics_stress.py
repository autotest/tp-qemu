import os
import logging
import time

from virttest import error_context
from virttest import utils_net
from virttest import utils_netperf
from virttest import utils_misc
from virttest import data_dir
from virttest import utils_test


def launch_netperf_client(test, server_ips, netperf_clients, test_option,
                          test_duration, netperf_para_sess,
                          netperf_cmd_prefix):
    """
    start netperf client in guest.
    """
    start_time = time.time()
    stop_time = start_time + test_duration * 1.5
    logging.info("server_ips = %s", server_ips)
    for s_ip in server_ips:
        for n_client in netperf_clients:
            n_client.bg_start(s_ip, test_option,
                              netperf_para_sess, netperf_cmd_prefix)
            if utils_misc.wait_for(n_client.is_netperf_running, 30, 0, 1,
                                   "Wait netperf test start"):
                logging.info("Netperf test start successfully.")
            else:
                test.error("Can not start netperf client.")

    for n_client in netperf_clients:
        if n_client.is_netperf_running():
            left_time = stop_time - time.time()
            utils_misc.wait_for(lambda: not
                                n_client.is_netperf_running(),
                                left_time, 0, 5,
                                "Wait netperf test finish %ss" % left_time)


@error_context.context_aware
def run(test, params, env):
    """
    Network stress with multi nics test with netperf.

    1) Start multi vm(s) guest.
    2) Select multi vm(s) or host to setup netperf server/client.
    3) Execute netperf  stress on multi nics.
    4) Ping test after netperf testing, check whether nics still work.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    login_timeout = float(params.get("login_timeout", 360))

    netperf_server = params.get("netperf_server").split()
    netperf_client = params.get("netperf_client")
    guest_username = params.get("username", "")
    guest_password = params.get("password", "")
    shell_client = params.get("shell_client")
    shell_port = params.get("shell_port")
    os_type = params.get("os_type")
    shell_prompt = params.get("shell_prompt", r"^root@.*[\#\$]\s*$|#")
    disable_firewall = params.get("disable_firewall", "service iptables stop;"
                                  " iptables -F")
    linesep = params.get(
        "shell_linesep", "\n").encode().decode('unicode_escape')
    status_test_command = params.get("status_test_command", "echo $?")
    ping_count = int(params.get("ping_count", 10))
    compile_option_client = params.get("compile_option_client", "")
    compile_option_server = params.get("compile_option_server", "")

    vms = params.get("vms")
    server_infos = []
    client_infos = []
    server_ips = []
    client_ips = []
    for server in netperf_server:
        s_info = {}
        if server in vms:
            server_vm = env.get_vm(server)
            server_vm.verify_alive()
            server_ctl = server_vm.wait_for_login(timeout=login_timeout)
            error_context.context("Stop fireware on netperf server guest.",
                                  logging.info)
            server_ctl.cmd(disable_firewall, ignore_all_errors=True)
            server_ip = server_vm.get_address()
            server_ips.append(server_ip)
            s_info["ip"] = server_ip
            s_info["os_type"] = params.get("os_type_%s" % server, os_type)
            s_info["username"] = params.get("username_%s" % server,
                                            guest_username)
            s_info["password"] = params.get("password_%s" % server,
                                            guest_password)
            s_info["shell_client"] = params.get("shell_client_%s" % server,
                                                shell_client)
            s_info["shell_port"] = params.get("shell_port_%s" % server,
                                              shell_port)
            s_info["shell_prompt"] = params.get("shell_prompt_%s" % server,
                                                shell_prompt)
            s_info["linesep"] = params.get("linesep_%s" % server,
                                           linesep)
            s_info["status_test_command"] = params.get("status_test_command_%s" % server,
                                                       status_test_command)
        else:
            err = "Only support setup netperf server in guest."
            test.error(err)
        server_infos.append(s_info)

    client = netperf_client.strip()
    c_info = {}
    if client in vms:
        client_vm = env.get_vm(client)
        client_vm.verify_alive()
        client_ctl = client_vm.wait_for_login(timeout=login_timeout)
        if params.get("dhcp_cmd"):
            status, output = client_ctl.cmd_status_output(params["dhcp_cmd"], timeout=600)
            if status:
                logging.warn("Failed to execute dhcp-command, output:\n %s" %
                             output)
        error_context.context("Stop fireware on netperf client guest.",
                              logging.info)
        client_ctl.cmd(disable_firewall, ignore_all_errors=True)

        client_ip = client_vm.get_address()
        client_ips.append(client_ip)
        params_client_nic = params.object_params(client)
        nics_count = len(params_client_nic.get("nics", "").split())
        if nics_count > 1:
            for i in range(nics_count)[1:]:
                client_vm.wait_for_login(nic_index=i, timeout=login_timeout)
                client_ips.append(client_vm.get_address(index=i))

        c_info["ip"] = client_ip
        c_info["os_type"] = params.get("os_type_%s" % client, os_type)
        c_info["username"] = params.get("username_%s" % client,
                                        guest_username)
        c_info["password"] = params.get("password_%s" % client,
                                        guest_password)
        c_info["shell_client"] = params.get("shell_client_%s" % client,
                                            shell_client)
        c_info["shell_port"] = params.get("shell_port_%s" % client,
                                          shell_port)
        c_info["shell_prompt"] = params.get("shell_prompt_%s" % client,
                                            shell_prompt)
        c_info["linesep"] = params.get("linesep_%s" % client,
                                       linesep)
        c_info["status_test_command"] = params.get("status_test_command_%s" % client,
                                                   status_test_command)
    else:
        err = "Only support setup netperf client in guest."
        test.error(err)
    client_infos.append(c_info)

    if params.get("os_type") == "linux":
        error_context.context("Config static route in netperf server guest.",
                              logging.info)
        nics_list = utils_net.get_linux_ifname(client_ctl)
        for ip in server_ips:
            index = server_ips.index(ip) % len(nics_list)
            client_ctl.cmd("route add  -host %s %s" % (ip, nics_list[index]))

    netperf_link = params.get("netperf_link")
    netperf_link = os.path.join(data_dir.get_deps_dir("netperf"), netperf_link)
    md5sum = params.get("pkg_md5sum")
    netperf_server_link = params.get("netperf_server_link_win", netperf_link)
    netperf_server_link = os.path.join(data_dir.get_deps_dir("netperf"),
                                       netperf_server_link)
    server_md5sum = params.get("server_md5sum")
    netperf_client_link = params.get("netperf_client_link_win", netperf_link)
    netperf_client_link = os.path.join(data_dir.get_deps_dir("netperf"),
                                       netperf_client_link)
    client_md5sum = params.get("client_md5sum")

    server_path_linux = params.get("server_path", "/var/tmp")
    client_path_linux = params.get("client_path", "/var/tmp")
    server_path_win = params.get("server_path_win", "c:\\")
    client_path_win = params.get("client_path_win", "c:\\")

    netperf_clients = []
    netperf_servers = []
    error_context.context("Setup netperf guest.", logging.info)
    for c_info in client_infos:
        if c_info["os_type"] == "windows":
            netperf_link_c = netperf_client_link
            client_path = client_path_win
            md5sum = client_md5sum
        else:
            netperf_link_c = netperf_link
            client_path = client_path_linux
        n_client = utils_netperf.NetperfClient(c_info["ip"],
                                               client_path,
                                               md5sum, netperf_link_c,
                                               client=c_info["shell_client"],
                                               port=c_info["shell_port"],
                                               username=c_info["username"],
                                               password=c_info["password"],
                                               prompt=c_info["shell_prompt"],
                                               linesep=c_info["linesep"],
                                               status_test_command=c_info["status_test_command"],
                                               compile_option=compile_option_client)
        netperf_clients.append(n_client)
    error_context.context("Setup netperf server.", logging.info)
    for s_info in server_infos:
        if s_info["os_type"] == "windows":
            netperf_link_s = netperf_server_link
            server_path = server_path_win
            md5sum = server_md5sum
        else:
            netperf_link_s = netperf_link
            server_path = server_path_linux
        n_server = utils_netperf.NetperfServer(s_info["ip"],
                                               server_path,
                                               md5sum, netperf_link_s,
                                               client=s_info["shell_client"],
                                               port=s_info["shell_port"],
                                               username=s_info["username"],
                                               password=s_info["password"],
                                               prompt=s_info["shell_prompt"],
                                               linesep=s_info["linesep"],
                                               status_test_command=s_info["status_test_command"],
                                               compile_option=compile_option_server)
        netperf_servers.append(n_server)

    try:
        error_context.context("Start netperf server.", logging.info)
        for n_server in netperf_servers:
            n_server.start()
        test_duration = int(params.get("netperf_test_duration", 60))
        test_protocols = params.get("test_protocols", "TCP_STREAM")
        netperf_sessions = params.get("netperf_sessions", "1")
        p_sizes = params.get("package_sizes")
        netperf_cmd_prefix = params.get("netperf_cmd_prefix", "")
        error_context.context("Start netperf clients.", logging.info)
        for protocol in test_protocols.split():
            error_context.context("Testing %s protocol" % protocol,
                                  logging.info)
            sessions_test = netperf_sessions.split()
            sizes_test = p_sizes.split()
            for size in sizes_test:
                for sess in sessions_test:
                    test_option = params.get("test_option", "")
                    test_option += " -t %s -l %s " % (protocol, test_duration)
                    test_option += " -- -m %s" % size
                    launch_netperf_client(test, server_ips, netperf_clients,
                                          test_option, test_duration, sess,
                                          netperf_cmd_prefix)
        error_context.context("Ping test after netperf testing.", logging.info)
        for s_ip in server_ips:
            status, output = utils_test.ping(s_ip, ping_count,
                                             timeout=float(ping_count) * 1.5)
            if status != 0:
                test.fail("Ping returns non-zero value %s" % output)

            package_lost = utils_test.get_loss_ratio(output)
            if package_lost != 0:
                test.fail("%s packeage lost when ping server ip %s " %
                          (package_lost, server))
    finally:
        for n_server in netperf_servers:
            if n_server:
                n_server.stop()
            n_server.package.env_cleanup(True)
        for n_client in netperf_clients:
            if n_client:
                n_client.package.env_cleanup(True)
        if server_ctl:
            server_ctl.close()
        if client_ctl:
            client_ctl.close()
