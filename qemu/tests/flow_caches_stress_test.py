import os
import time

from avocado.utils import process
from virttest import data_dir, env_process, error_context, utils_net, utils_netperf


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU flow caches stress test case, only for linux

    1) Make sure nf_conntrack is disabled in host and guest.
       If nf_conntrack is enabled in host, skip this case.
    2) Boot guest with vhost=on/off.
    3) Enable multi queues support in guest (optional).
    4) After installation of netperf, run netserver in host.
    5) Run netperf TCP_CRR protocal test in guest.
    6) Transfer file between guest and host.
    7) Check the md5 of copied file.

    This is a sample QEMU test, so people can get used to some of the test APIs.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def get_if_queues(ifname):
        """
        Query interface queues with 'ethtool -l'

        :param ifname: interface name
        """
        cmd = "ethtool -l %s" % ifname
        out = session.cmd_output(cmd)
        test.log.info(out)

    nf_conntrack_max_set_cmd = params.get("nf_conntrack_max_set")
    test.log.info("nf_conntrack_max_set_cmd is %s", nf_conntrack_max_set_cmd)
    msg = "Make sure nf_conntrack is disabled in host and guest."
    error_context.context(msg, test.log.info)
    if str.encode("nf_conntrack") in process.system_output("lsmod"):
        process.system_output(nf_conntrack_max_set_cmd)

    params["start_vm"] = "yes"
    error_context.context("Boot up guest", test.log.info)
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    if "nf_conntrack" in session.cmd_output("lsmod"):
        msg = "Unload nf_conntrack module in guest."
        error_context.context(msg, test.log.info)
        black_str = (
            "#disable nf_conntrack\\nblacklist nf_conntrack\\n"
            "blacklist nf_conntrack_ipv6\\nblacklist xt_conntrack\\n"
            "blacklist nf_conntrack_ftp\\nblacklist xt_state\\n"
            "blacklist iptable_nat\\nblacklist ipt_REDIRECT\\n"
            "blacklist nf_nat\\nblacklist nf_conntrack_ipv4"
        )
        cmd = "echo -e '%s' >> /etc/modprobe.d/blacklist.conf" % black_str
        session.cmd(cmd)
        session = vm.reboot(session, timeout=timeout)
        if "nf_conntrack" in session.cmd_output("lsmod"):
            err = "nf_conntrack module still running in guest, "
            err += "set nf_conntrack_max instead."
            error_context.context(err, test.log.info)
            session.cmd(nf_conntrack_max_set_cmd)

    netperf_link = os.path.join(
        data_dir.get_deps_dir("netperf"), params.get("netperf_link")
    )
    md5sum = params.get("pkg_md5sum")
    client_num = params.get("netperf_client_num", 520)
    netperf_timeout = int(params.get("netperf_timeout", 600))
    disable_firewall = params.get("disable_firewall", "")

    if int(params.get("queues", 1)) > 1 and params.get("os_type") == "linux":
        error_context.context("Enable multi queues support in guest.", test.log.info)
        guest_mac = vm.get_mac_address()
        ifname = utils_net.get_linux_ifname(session, guest_mac)
        get_if_queues(ifname)

        try:
            cmd = "ethtool -L %s combined %s" % (ifname, params.get("queues"))
            status, out = session.cmd_status_output(cmd)
        except Exception as err:
            get_if_queues(ifname)
            msg = "Fail to enable multi queues support in guest."
            msg += f"Got error: {err}"
            test.error(msg)
        test.log.info("Command %s set queues succeed", cmd)

    error_context.context("Setup netperf in guest", test.log.info)
    if params.get("os_type") == "linux":
        session.cmd(disable_firewall, ignore_all_errors=True)
        g_client_link = netperf_link
        g_client_path = params.get("client_path", "/var/tmp/")
    else:
        raise ValueError("unsupported os type")
    netperf_client_ip = vm.get_address()
    username = params.get("username", "root")
    password = params.get("password", "123456")
    client = params.get("shell_client", "ssh")
    port = params.get("shell_port", "22")
    prompt = params.get("shell_prompt", r"^root@.*[\#\$]\s*$|#")
    linesep = params.get("shell_linesep", "\n").encode().decode("unicode_escape")
    status_test_command = params.get("status_test_command", "echo $?")
    compile_option_client = params.get("compile_option_client", "")
    netperf_client = utils_netperf.NetperfClient(
        netperf_client_ip,
        g_client_path,
        md5sum,
        g_client_link,
        client,
        port,
        username=username,
        password=password,
        prompt=prompt,
        linesep=linesep,
        status_test_command=status_test_command,
        compile_option=compile_option_client,
    )

    error_context.context("Setup netperf in host", test.log.info)
    host_ip = utils_net.get_host_ip_address(params)
    server_path = params.get("server_path", "/var/tmp/")
    server_shell_client = params.get("server_shell_client", "ssh")
    server_shell_port = params.get("server_shell_port", "22")
    server_passwd = params["hostpasswd"]
    server_username = params.get("host_username", "root")
    compile_option_server = params.get("compile_option_server", "")
    netperf_server = utils_netperf.NetperfServer(
        host_ip,
        server_path,
        md5sum,
        netperf_link,
        server_shell_client,
        server_shell_port,
        username=server_username,
        password=server_passwd,
        prompt=prompt,
        linesep=linesep,
        status_test_command=status_test_command,
        compile_option=compile_option_server,
    )
    try:
        error_context.base_context("Run netperf test between host and guest.")
        error_context.context("Start netserver in host.", test.log.info)
        netperf_server.start()

        error_context.context(
            "Start Netperf in guest for %ss." % netperf_timeout, test.log.info
        )
        test_option = "-t TCP_CRR -l %s -- -b 10 -D" % netperf_timeout
        netperf_client.bg_start(host_ip, test_option, client_num)
        start_time = time.time()
        deviation_time = params.get_numeric("deviation_time")
        duration = time.time() - start_time
        max_run_time = netperf_timeout + deviation_time
        while duration < max_run_time:
            time.sleep(10)
            duration = time.time() - start_time
            status = netperf_client.is_netperf_running()
            if not status and duration < netperf_timeout - 10:
                test.fail("netperf terminated unexpectedly")
            test.log.info("Wait netperf test finish %ss", duration)
        if netperf_client.is_netperf_running():
            test.fail("netperf still running, netperf hangs")
        else:
            test.log.info("netperf runs successfully")
    finally:
        netperf_server.stop()
        netperf_client.cleanup(True)
        netperf_server.cleanup(True)
        if session:
            session.close()
