import logging

from avocado.utils import process

from virttest import error_context
from virttest import utils_netperf
from virttest import utils_net
from virttest import env_process
from virttest import utils_misc
from virttest import data_dir
from virttest import utils_test


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU flow caches stress test test

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
    msg = "Make sure nf_conntrack is disabled in host and guest."
    error_context.context(msg, logging.info)
    if "nf_conntrack" in process.system_output("lsmod"):
        err = "nf_conntrack load in host, skip this case"
        test.cancel(err)

    params["start_vm"] = "yes"
    error_context.context("Boot up guest", logging.info)
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=timeout)
    if "nf_conntrack" in session.cmd_output("lsmod"):
        msg = "Unload nf_conntrack module in guest."
        error_context.context(msg, logging.info)
        black_str = "#disable nf_conntrack\\nblacklist nf_conntrack\\n" \
                    "blacklist nf_conntrack_ipv6\\nblacklist xt_conntrack\\n" \
                    "blacklist nf_conntrack_ftp\\nblacklist xt_state\\n" \
                    "blacklist iptable_nat\\nblacklist ipt_REDIRECT\\n" \
                    "blacklist nf_nat\\nblacklist nf_conntrack_ipv4"
        cmd = "echo -e '%s' >> /etc/modprobe.d/blacklist.conf" % black_str
        session.cmd(cmd)
        session = vm.reboot(session, timeout=timeout)
        if "nf_conntrack" in session.cmd_output("lsmod"):
            err = "Fail to unload nf_conntrack module in guest."
            test.error(err)

    netperf_link = utils_misc.get_path(data_dir.get_deps_dir("netperf"),
                                       params["netperf_link"])
    md5sum = params.get("pkg_md5sum")
    win_netperf_link = params.get("win_netperf_link")
    if win_netperf_link:
        win_netperf_link = utils_misc.get_path(data_dir.get_deps_dir("netperf"),
                                               win_netperf_link)
    win_netperf_md5sum = params.get("win_netperf_md5sum")
    server_path = params.get("server_path", "/var/tmp/")
    client_path = params.get("client_path", "/var/tmp/")
    win_netperf_path = params.get("win_netperf_path", "c:\\")
    client_num = params.get("netperf_client_num", 520)
    netperf_timeout = int(params.get("netperf_timeout", 600))
    netperf_client_ip = vm.get_address()
    host_ip = utils_net.get_host_ip_address(params)
    netperf_server_ip = params.get("netperf_server_ip", host_ip)

    username = params.get("username", "root")
    password = params.get("password", "123456")
    passwd = params.get("hostpasswd", "123456")
    client = params.get("shell_client", "ssh")
    port = params.get("shell_port", "22")
    prompt = params.get("shell_prompt", r"^root@.*[\#\$]\s*$|#")
    linesep = params.get("shell_linesep", "\n").decode('string_escape')
    status_test_command = params.get("status_test_command", "echo $?")

    compile_option_client = params.get("compile_option_client", "")
    compile_option_server = params.get("compile_option_server", "")

    if int(params.get("queues", 1)) > 1 and params.get("os_type") == "linux":
        error_context.context("Enable multi queues support in guest.",
                              logging.info)
        guest_mac = vm.get_mac_address()
        ifname = utils_net.get_linux_ifname(session, guest_mac)
        cmd = "ethtool -L %s combined  %s" % (ifname, params.get("queues"))
        status, out = session.cmd_status_output(cmd)
        msg = "Fail to enable multi queues support in guest."
        msg += "Command %s fail output: %s" % (cmd, out)
        test.error(msg)

    if params.get("os_type") == "linux":
        session.cmd("iptables -F", ignore_all_errors=True)
        g_client_link = netperf_link
        g_client_path = client_path
        g_md5sum = md5sum
    elif params.get("os_type") == "windows":
        g_client_link = win_netperf_link
        g_client_path = win_netperf_path
        g_md5sum = win_netperf_md5sum

    error_context.context("Setup netperf in guest and host", logging.info)
    netperf_client = utils_netperf.NetperfClient(netperf_client_ip,
                                                 g_client_path,
                                                 g_md5sum, g_client_link,
                                                 username=username,
                                                 password=password,
                                                 prompt=prompt,
                                                 linesep=linesep,
                                                 status_test_command=status_test_command,
                                                 compile_option=compile_option_client)

    netperf_server = utils_netperf.NetperfServer(netperf_server_ip,
                                                 server_path,
                                                 md5sum,
                                                 netperf_link,
                                                 client, port,
                                                 password=passwd,
                                                 prompt=prompt,
                                                 linesep=linesep,
                                                 status_test_command=status_test_command,
                                                 compile_option=compile_option_server)
    try:
        error_context.base_context("Run netperf test between host and guest.")
        error_context.context("Start netserver in host.", logging.info)
        netperf_server.start()

        error_context.context("Start Netperf in guest for %ss."
                              % netperf_timeout, logging.info)
        test_option = "-t TCP_CRR -l %s -- -b 10 -D" % netperf_timeout
        netperf_client.bg_start(netperf_server_ip, test_option, client_num)

        utils_misc.wait_for(lambda: not netperf_client.is_netperf_running(),
                            timeout=netperf_timeout, first=590, step=2)

        utils_test.run_file_transfer(test, params, env)
    finally:
        netperf_server.stop()
        netperf_client.package.env_cleanup(True)
        if session:
            session.close()
