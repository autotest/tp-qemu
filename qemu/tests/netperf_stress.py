import os
import time

from virttest import (
    data_dir,
    env_process,
    error_context,
    utils_misc,
    utils_net,
    utils_netperf,
)


@error_context.context_aware
def run(test, params, env):
    """
    Run netperf stress on server and client side.

    1) Start multi vm(s) guest.
    2) Select multi vm(s) or host to setup netperf server/client.
    3) Run netperf stress test.
    4) Finish test until timeout env["netperf_run"] is False.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def netperf_test(duration):
        while duration < max_run_time:
            time.sleep(10)
            duration = time.time() - start_time
            status = n_client.is_netperf_running()
            if not status and duration < test_duration - 10:
                msg = "netperf terminated unexpectedly"
                test.fail(msg)
                return False, msg
            test.log.info("Wait netperf test finish %ss", duration)
        if n_client.is_netperf_running():
            msg = "netperf still running, netperf hangs"
            test.fail(msg)
            return False, msg
        else:
            test.log.info("netperf runs successfully")

    login_timeout = float(params.get("login_timeout", 360))
    netperf_server = params.get("netperf_server").split()
    netperf_client = params.get("netperf_client").split()
    guest_username = params.get("username", "")
    guest_password = params.get("password", "")
    host_password = params.get("hostpassword", "redhat")
    shell_client = params.get("shell_client")
    shell_port = params.get("shell_port")
    os_type = params.get("os_type")
    shell_prompt = params.get("shell_prompt", r"^root@.*[\#\$]\s*$|#")
    linesep = params.get("shell_linesep", "\n").encode().decode("unicode_escape")
    status_test_command = params.get("status_test_command", "echo $?")
    compile_option_client = params.get("compile_option_client", "")
    compile_option_server = params.get("compile_option_server", "")
    disable_firewall = params.get("disable_firewall", "")
    if params.get("netperf_vlan_test", "no") == "yes" and params.get("host_vlan_ip"):
        host_ip = params.get("host_vlan_ip")
    else:
        host_ip = utils_net.get_host_ip_address(params)

    vms = params.get("vms")
    server_infos = []
    client_infos = []
    for server in netperf_server:
        s_info = {}
        if server in vms:
            if params.get("os_type") == "windows":
                if (
                    params.get_numeric("smp") > 32
                    or params.get_numeric("vcpu_maxcpus") > 32
                ):
                    params["smp"] = params["vcpu_maxcpus"] = 32
                params["start_vm"] = "yes"
                env_process.preprocess_vm(test, params, env, server)
            server_vm = env.get_vm(server)
            server_vm.verify_alive()
            session = server_vm.wait_for_login(timeout=login_timeout)
            session.cmd(disable_firewall, ignore_all_errors=True)
            if params.get("netperf_vlan_test", "no") == "yes":
                vlan_nic = params.get("vlan_nic")
                server_ip = utils_net.get_linux_ipaddr(session, vlan_nic)[0]
            else:
                server_ip = server_vm.get_address()

            s_info["ip"] = server_ip
            s_info["os_type"] = params.get("os_type_%s" % server, os_type)
            s_info["username"] = params.get("username_%s" % server, guest_username)
            s_info["password"] = params.get("password_%s" % server, guest_password)
            s_info["shell_client"] = params.get(
                "shell_client_%s" % server, shell_client
            )
            s_info["shell_port"] = params.get("shell_port_%s" % server, shell_port)
            s_info["shell_prompt"] = params.get(
                "shell_prompt_%s" % server, shell_prompt
            )
            s_info["linesep"] = params.get("linesep_%s" % server, linesep)
            s_info["status_test_command"] = params.get(
                "status_test_command_%s" % server, status_test_command
            )
        else:
            if server == "localhost":
                s_info["ip"] = host_ip
                s_info["password"] = params.get("password_%s" % server, host_password)
            else:
                s_info["ip"] = server
                s_info["password"] = params.get("password_%s" % server, "redhat")
            s_info["os_type"] = params.get("os_type_%s" % server, "linux")
            s_info["username"] = params.get("username_%s" % server, "root")
            s_info["shell_client"] = params.get("shell_client_%s" % server, "ssh")
            s_info["shell_port"] = params.get("shell_port_%s" % server, "22")
            s_info["shell_prompt"] = params.get(
                "shell_prompt_%s" % server, r"^\[.*\][\#\$]\s*$"
            )
            s_info["linesep"] = params.get("linesep_%s" % server, "\n")
            s_info["status_test_command"] = params.get(
                "status_test_command_%s" % server, "echo $?"
            )
        server_infos.append(s_info)

    for client in netperf_client:
        c_info = {}
        if client in vms:
            client_vm = env.get_vm(client)
            client_vm.verify_alive()
            session = client_vm.wait_for_login(timeout=login_timeout)
            session.cmd(disable_firewall, ignore_all_errors=True)
            if params.get("netperf_vlan_test", "no") == "yes":
                vlan_nic = params.get("vlan_nic")
                client_ip = utils_net.get_linux_ipaddr(session, vlan_nic)[0]
            else:
                client_ip = client_vm.get_address()
            c_info["ip"] = client_ip
            c_info["os_type"] = params.get("os_type_%s" % client, os_type)
            c_info["username"] = params.get("username_%s" % client, guest_username)
            c_info["password"] = params.get("password_%s" % client, guest_password)
            c_info["shell_client"] = params.get(
                "shell_client_%s" % client, shell_client
            )
            c_info["shell_port"] = params.get("shell_port_%s" % client, shell_port)
            c_info["shell_prompt"] = params.get(
                "shell_prompt_%s" % client, shell_prompt
            )
            c_info["linesep"] = params.get("linesep_%s" % client, linesep)
            c_info["status_test_command"] = params.get(
                "status_test_command_%s" % client, status_test_command
            )
        else:
            if client == "localhost":
                c_info["ip"] = host_ip
                c_info["password"] = params.get("password_%s" % client, host_password)
            else:
                c_info["ip"] = client
                c_info["password"] = params.get("password_%s" % client, "redhat")
            c_info["os_type"] = params.get("os_type_%s" % client, "linux")
            c_info["username"] = params.get("username_%s" % client, "root")
            c_info["shell_client"] = params.get("shell_client_%s" % client, "ssh")
            c_info["shell_port"] = params.get("shell_port_%s" % client, "23")
            c_info["shell_prompt"] = params.get(
                "shell_prompt_%s" % client, r"^\[.*\][\#\$]\s*$"
            )
            c_info["linesep"] = params.get("linesep_%s" % client, "\n")
            c_info["status_test_command"] = params.get(
                "status_test_command_%s" % client, "echo $?"
            )
        client_infos.append(c_info)

    netperf_link = params.get("netperf_link")
    netperf_link = os.path.join(data_dir.get_deps_dir("netperf"), netperf_link)
    md5sum = params.get("pkg_md5sum")
    netperf_server_link = params.get("netperf_server_link_win", netperf_link)
    netperf_server_link = os.path.join(
        data_dir.get_deps_dir("netperf"), netperf_server_link
    )
    server_md5sum = params.get("server_md5sum")
    netperf_client_link = params.get("netperf_client_link_win", netperf_link)
    netperf_client_link = os.path.join(
        data_dir.get_deps_dir("netperf"), netperf_client_link
    )
    client_md5sum = params.get("client_md5sum")

    server_path_linux = params.get("server_path", "/var/tmp")
    client_path_linux = params.get("client_path", "/var/tmp")
    server_path_win = params.get("server_path_win", "c:\\")
    client_path_win = params.get("client_path_win", "c:\\")

    netperf_clients = []
    netperf_servers = []
    for c_info in client_infos:
        if c_info["os_type"] == "windows":
            netperf_link_c = netperf_client_link
            client_path = client_path_win
            md5sum = client_md5sum
        else:
            netperf_link_c = netperf_link
            client_path = client_path_linux
        n_client = utils_netperf.NetperfClient(
            c_info["ip"],
            client_path,
            md5sum,
            netperf_link_c,
            client=c_info["shell_client"],
            port=c_info["shell_port"],
            username=c_info["username"],
            password=c_info["password"],
            prompt=c_info["shell_prompt"],
            linesep=c_info["linesep"],
            status_test_command=c_info["status_test_command"],
            compile_option=compile_option_client,
        )
        netperf_clients.append(n_client)

    for s_info in server_infos:
        if s_info["os_type"] == "windows":
            netperf_link_s = netperf_server_link
            server_path = server_path_win
            md5sum = server_md5sum
        else:
            netperf_link_s = netperf_link
            server_path = server_path_linux
        n_server = utils_netperf.NetperfServer(
            s_info["ip"],
            server_path,
            md5sum,
            netperf_link_s,
            client=s_info["shell_client"],
            port=s_info["shell_port"],
            username=s_info["username"],
            password=s_info["password"],
            prompt=s_info["shell_prompt"],
            linesep=s_info["linesep"],
            status_test_command=s_info["status_test_command"],
            compile_option=compile_option_server,
        )
        netperf_servers.append(n_server)

    # Get range of message size.
    try:
        for n_server in netperf_servers:
            n_server.start()
        # Run netperf with message size defined in range.
        test_duration = int(params.get("netperf_test_duration", 60))
        deviation_time = params.get_numeric("deviation_time")
        netperf_para_sess = params.get("netperf_para_sessions", "1")
        test_protocols = params.get("test_protocols", "TCP_STREAM")
        netperf_cmd_prefix = params.get("netperf_cmd_prefix", "")
        netperf_output_unit = params.get("netperf_output_unit", " ")
        netperf_package_sizes = params.get("netperf_package_sizes")
        test_option = params.get("test_option", "")
        test_option += " -l %s" % test_duration
        if params.get("netperf_remote_cpu") == "yes":
            test_option += " -C"
        if params.get("netperf_local_cpu") == "yes":
            test_option += " -c"
        if netperf_output_unit in "GMKgmk":
            test_option += " -f %s" % netperf_output_unit
        num = 0
        s_len = len(server_infos)
        for protocol in test_protocols.split():
            error_context.context("Testing %s protocol" % protocol, test.log.info)
            t_option = "%s -t %s" % (test_option, protocol)
            for n_client in netperf_clients:
                index = num % s_len
                server_ip = server_infos[index]["ip"]
                n_client.bg_start(
                    server_ip,
                    t_option,
                    netperf_para_sess,
                    netperf_cmd_prefix,
                    package_sizes=netperf_package_sizes,
                )
                if utils_misc.wait_for(
                    n_client.is_netperf_running, 10, 0, 3, "Wait netperf test start"
                ):
                    test.log.info("Netperf test start successfully.")
                else:
                    test.error("Can not start netperf client.")
                num += 1
            start_time = time.time()
            # here when set a run flag, when other case call this case as a
            # subprocess backgroundly, can set this run flag to False to stop
            # the stress test.
            env["netperf_run"] = True
            duration = time.time() - start_time
            max_run_time = test_duration + deviation_time
            netperf_test(duration)
    finally:
        for n_server in netperf_servers:
            n_server.stop()
            n_server.cleanup(True)
        for n_client in netperf_clients:
            n_client.stop()
            n_client.cleanup(True)
        env["netperf_run"] = False
        if session:
            session.close()
