import os
import re

from virttest import data_dir, error_context, utils_net, utils_netperf


@error_context.context_aware
def run(test, params, env):
    """
    Run netperf on server and client side, we need run this case on two
    machines. If dsthost is not set will start netperf server on local
    host and log a error message.:
    1) Start one vm guest os as client or server
       (windows guest must using as server).
    2) Start a reference machine (dsthost) as server/client.
    3) Setup netperf on guest and reference machine (dsthost).
    4) Start netperf server on the server host.
    5) Run netperf client command in guest several time with different
       message size.
    6) Compare UDP performance to make sure it is acceptable.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    login_timeout = float(params.get("login_timeout", 360))
    dsthost = params.get("dsthost", "localhost")

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    main_vm_ip = vm.get_address()
    session.cmd("iptables -F", ignore_all_errors=True)

    error_context.context("Test env prepare", test.log.info)
    netperf_link = params.get("netperf_link")
    if netperf_link:
        netperf_link = os.path.join(data_dir.get_deps_dir("netperf"), netperf_link)
    md5sum = params.get("pkg_md5sum")
    netperf_server_link = params.get("netperf_server_link_win")
    if netperf_server_link:
        netperf_server_link = os.path.join(
            data_dir.get_deps_dir("netperf"), netperf_server_link
        )
    netperf_client_link = params.get("netperf_client_link_win")
    if netperf_client_link:
        netperf_client_link = os.path.join(
            data_dir.get_deps_dir("netperf"), netperf_client_link
        )

    server_md5sum = params.get("server_md5sum")
    client_md5sum = params.get("client_md5sum")
    os_type = params.get("os_type")
    server_path = params.get("server_path", "/var/tmp/")
    client_path = params.get("client_path", "/var/tmp/")
    server_path_win = params.get("server_path_win", "c:\\")
    client_path_win = params.get("client_path_win", "c:\\")
    guest_username = params.get("username", "")
    guest_password = params.get("password", "")
    params.get("hostpassword")
    client = params.get("shell_client")
    port = params.get("shell_port")
    prompt = params.get("shell_prompt", r"^root@.*[\#\$]\s*$|#")
    linesep = params.get("shell_linesep", "\n").encode().decode("unicode_escape")
    status_test_command = params.get("status_test_command", "echo $?")
    compile_option_client = params.get("compile_option_client", "")
    compile_option_server = params.get("compile_option_server", "")

    if dsthost in params.get("vms", "vm1 vm2"):
        server_vm = env.get_vm(dsthost)
        server_vm.verify_alive()
        s_session = server_vm.wait_for_login(timeout=login_timeout)
        s_session.cmd("iptables -F", ignore_all_errors=True)
        netserver_ip = server_vm.get_address()
        s_session.close()
        s_client = client
        s_port = port
        s_username = guest_username
        s_password = guest_password
        if os_type == "windows":
            s_link = netperf_server_link
            s_path = server_path_win
            s_md5sum = server_md5sum
        else:
            s_link = netperf_link
            s_path = server_path
            s_md5sum = md5sum
    else:
        if re.match(r"((\d){1,3}\.){3}(\d){1,3}", dsthost):
            netserver_ip = dsthost
        else:
            server_interface = params.get("netdst", "switch")
            host_nic = utils_net.Interface(server_interface)
            netserver_ip = host_nic.get_ip()
        s_client = params.get("shell_client_%s" % dsthost, "ssh")
        s_port = params.get("shell_port_%s" % dsthost, "22")
        s_username = params.get("username_%s" % dsthost, "root")
        s_password = params.get("password_%s" % dsthost, "redhat")
        s_link = netperf_link
        s_path = server_path
        s_md5sum = md5sum

    if os_type == "windows":
        c_path = client_path_win
        c_md5sum = client_md5sum
        c_link = netperf_client_link
    else:
        c_path = client_path
        c_md5sum = md5sum
        c_link = netperf_link

    netperf_client = utils_netperf.NetperfClient(
        main_vm_ip,
        c_path,
        c_md5sum,
        c_link,
        client,
        port,
        username=guest_username,
        password=guest_password,
        prompt=prompt,
        linesep=linesep,
        status_test_command=status_test_command,
        compile_option=compile_option_client,
    )

    netperf_server = utils_netperf.NetperfServer(
        netserver_ip,
        s_path,
        s_md5sum,
        s_link,
        s_client,
        s_port,
        username=s_username,
        password=s_password,
        prompt=prompt,
        linesep=linesep,
        status_test_command=status_test_command,
        compile_option=compile_option_server,
    )

    # Get range of message size.
    message_size = params.get("message_size_range", "580 590 1").split()
    start_size = int(message_size[0])
    end_size = int(message_size[1])
    step = int(message_size[2])
    m_size = start_size
    throughput = []

    try:
        error_context.context("Start netperf_server", test.log.info)
        netperf_server.start()
        # Run netperf with message size defined in range.
        msg = "Detail result of netperf test with different packet size.\n"
        for m_size in range(start_size, end_size + 1, step):
            test_protocol = params.get("test_protocol", "UDP_STREAM")
            test_option = "-t %s -- -m %s" % (test_protocol, m_size)
            txt = "Run netperf client with protocol: '%s', packet size: '%s'"
            error_context.context(txt % (test_protocol, m_size), test.log.info)
            output = netperf_client.start(netserver_ip, test_option)
            re_str = r"[0-9\.]+\s+[0-9\.]+\s+[0-9\.]+\s+[0-9\.]+\s+[0-9\.]+"
            re_str += r"\s+[0-9\.]+"
            try:
                line_tokens = re.findall(re_str, output)[0].split()
            except IndexError:
                txt = "Fail to get Throughput for %s." % m_size
                txt += " netprf client output: %s" % output
                test.error(txt)
            if not line_tokens:
                test.error("Output format is not expected")
            throughput.append(float(line_tokens[5]))
            msg += output
    finally:
        test.log.debug("Kill netperf server")
        netperf_server.stop()
        try:
            test.log.debug("Cleanup env on both server and client")
            netperf_server.cleanup()
            netperf_client.cleanup()
        except Exception as e:
            test.log.warning("Cleanup failed:\n%s\n", e)

    with open(os.path.join(test.debugdir, "udp_results"), "w") as result_file:
        result_file.write(msg)
    failratio = float(params.get("failratio", 0.3))
    error_context.context("Compare UDP performance.", test.log.info)
    for i in range(len(throughput) - 1):
        if abs(throughput[i] - throughput[i + 1]) > throughput[i] * failratio:
            txt = "The gap between adjacent throughput is greater than"
            txt += "%f." % failratio
            txt += "Please refer to log file for details:\n %s" % msg
            test.fail(txt)
    test.log.info("The UDP performance as measured via netperf is ok.")
    test.log.info("Throughput of netperf command: %s", throughput)
    test.log.debug("Output of netperf command:\n %s", msg)

    try:
        if session:
            session.close()
    except Exception:
        pass
