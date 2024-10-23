import glob
import itertools
import os
import re
import shutil
import time

from avocado.utils import path as utils_path
from avocado.utils import process
from virttest import data_dir, error_context, utils_netperf


@error_context.context_aware
def run(test, params, env):
    """
     Test Qos between guests in one ovs backend

    1) Boot the vms
    2) Apply QoS limitation to 1Mbps on the tap of a guest.
    3) Start netperf server on another guest.
    4) Start netperf client on guest in step 1 with option -l 60.
    5) Stop netperf client and set QoS to 10Mbps.
    6) Run step 4 again.
    7) Verify vm through out.

    :param test: Kvm test object
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def set_ovs_port_attr(iface, attribute, value):
        """
        Set OVS port attribute.
        """
        cmd = "ovs-vsctl set interface %s %s=%s" % (iface, attribute, value)
        test.log.info("execute host command: %s", cmd)
        status = process.system(cmd, ignore_status=True)
        if status != 0:
            err_msg = "set %s to %s for interface '%s' " % (attribute, value, iface)
            err_msg += "exited with nozero statu '%d'" % status
            test.error(err_msg)

    def set_port_qos(vm, rate, burst):
        """
        Set ingress_policing_rate and ingress_policing_burst for tap device
        used by vm.

        :param vm: netperf client vm object
        :param rate: value of ingress_policing_rate
        :param brust: value of ingress_policing_brust
        """
        iface = vm.get_ifname()
        error_context.context(
            "Set QoS for tap '%s' use by vm '%s'" % (iface, vm.name), test.log.info
        )
        attributes = zip(
            ["ingress_policing_rate", "ingress_policing_burst"], [rate, burst]
        )
        for k, v in attributes:
            set_ovs_port_attr(iface, k, v)
            time.sleep(0.1)

    def get_throughout(
        netperf_server, server_vm, netperf_client, client_vm, client_options=" -l 60"
    ):
        """
        Get network throughout by netperf.

        :param netperf_server: utils_netperf.NetperfServer instance.
        :param server_ip: ip address of netperf server.
        :param netperf_client: utils_netperf.NetperfClient instance.
        :param client_options: netperf client start options.

        :return: float type throughout Kbps.
        """
        error_context.context(
            "Set '%s' as netperf server" % server_vm.name, test.log.info
        )
        if not netperf_server.is_server_running():
            netperf_server.start()

        error_context.context(
            "Set '%s' as netperf client" % client_vm.name, test.log.info
        )
        server_ip = server_vm.get_address()
        output = netperf_client.start(server_ip, client_options)
        test.log.debug("netperf client output: %s", output)
        regex = r"\d+\s+\d+\s+\d+\s+[\d.]+\s+([\d.]+)"
        try:
            throughout = float(re.search(regex, output, re.M).groups()[0])
            return throughout * 1000
        except Exception:
            test.error("Invaild output format of netperf client!")
        finally:
            netperf_client.stop()

    def is_test_pass(data):
        """
        Check throughout near gress_policing_rate set for tap device.
        """
        return data[1] <= data[2] + data[3]

    def report_test_results(datas):
        """
        Report failed test scenarios.
        """
        error_context.context("Analyze guest throughout", test.log.info)
        fails = [_ for _ in datas if not is_test_pass(_)]
        if fails:
            msg = "OVS Qos test failed, "
            for tap, throughout, rate, burst in fails:
                msg += "netperf throughout(%s) on '%s' " % (throughout, tap)
                msg += "should be near ingress_policing_rate(%s), " % rate
                msg += "ingress_policing_burst is %s;\n" % burst
            test.fail(msg)

    def clear_qos_setting(iface):
        error_context.context(
            "Clear qos setting for ovs port '%s'" % iface, test.log.info
        )
        clear_cmd = "ovs-vsctl clear Port %s qos" % iface
        process.system(clear_cmd)
        test.log.info("Clear ovs command: %s", clear_cmd)

    def setup_netperf_env():
        """
        Setup netperf envrioments in vms
        """

        def __get_vminfo():
            """
            Get vms information;
            """
            login_timeout = float(params.get("login_timeout", 360))
            stop_firewall_cmd = "systemctl stop firewalld||"
            stop_firewall_cmd += "service firewalld stop"
            guest_info = [
                "status_test_command",
                "shell_linesep",
                "shell_prompt",
                "username",
                "password",
                "shell_client",
                "shell_port",
                "os_type",
            ]
            vms_info = []
            for _ in params.get("vms").split():
                info = list(map(lambda x: params.object_params(_).get(x), guest_info))
                vm = env.get_vm(_)
                vm.verify_alive()
                session = vm.wait_for_login(timeout=login_timeout)
                session.cmd(stop_firewall_cmd, ignore_all_errors=True)
                vms_info.append((vm, info))
            return vms_info

        netperf_link = params.get("netperf_link")
        netperf_link = os.path.join(data_dir.get_deps_dir("netperf"), netperf_link)
        md5sum = params.get("pkg_md5sum")
        netperf_server_link = params.get("netperf_server_link_win", netperf_link)
        netperf_server_link = os.path.join(
            data_dir.get_deps_dir("netperf"), netperf_server_link
        )
        netperf_client_link = params.get("netperf_client_link_win", netperf_link)
        netperf_client_link = os.path.join(
            data_dir.get_deps_dir("netperf"), netperf_client_link
        )

        server_path_linux = params.get("server_path", "/var/tmp")
        client_path_linux = params.get("client_path", "/var/tmp")
        server_path_win = params.get("server_path_win", "c:\\")
        client_path_win = params.get("client_path_win", "c:\\")
        compile_option_client = params.get("compile_option_client", "")
        compile_option_server = params.get("compile_option_server", "")

        netperf_servers, netperf_clients = [], []
        for idx, (vm, info) in enumerate(__get_vminfo()):
            if idx % 2 == 0:
                if info[-1] == "windows":
                    netperf_link = netperf_server_link
                    server_path = server_path_win
                else:
                    netperf_link = netperf_link
                    server_path = server_path_linux
                server = utils_netperf.NetperfServer(
                    vm.get_address(),
                    server_path,
                    md5sum,
                    netperf_link,
                    port=info[-2],
                    client=info[-3],
                    password=info[-4],
                    username=info[-5],
                    prompt=info[-6],
                    linesep=info[-7].encode().decode("unicode_escape"),
                    status_test_command=info[-8],
                    compile_option=compile_option_server,
                )
                netperf_servers.append((server, vm))
                continue
            else:
                if info[-1] == "windows":
                    netperf_link = netperf_client_link
                    client_path = client_path_win
                else:
                    netperf_link = netperf_link
                    client_path = client_path_linux
                client = utils_netperf.NetperfClient(
                    vm.get_address(),
                    client_path,
                    md5sum,
                    netperf_link,
                    port=info[-2],
                    client=info[-3],
                    password=info[-4],
                    username=info[-5],
                    prompt=info[-6],
                    linesep=info[-7].encode().decode("unicode_escape"),
                    status_test_command=info[-8],
                    compile_option=compile_option_client,
                )
                netperf_clients.append((client, vm))
                continue
        return netperf_clients, netperf_servers

    utils_path.find_command("ovs-vsctl")
    if params.get("netdst") not in process.system_output("ovs-vsctl show").decode():
        test.error("This is a openvswitch only test")
    extra_options = params.get("netperf_client_options", " -l 60")
    rate_brust_pairs = params.get("rate_brust_pairs").split()
    rate_brust_pairs = list(map(lambda x: map(int, x.split(",")), rate_brust_pairs))
    results = []
    try:
        netperf_clients, netperf_servers = setup_netperf_env()
        for idx in range(len(netperf_clients)):
            netperf_client, client_vm = netperf_clients[idx]
            idx = (idx < len(netperf_servers) and [idx] or [0])[0]
            netperf_server, server_vm = netperf_servers[idx]
            for rate, burst in rate_brust_pairs:
                set_port_qos(client_vm, rate, burst)
                time.sleep(3)
                throughout = get_throughout(
                    netperf_server, server_vm, netperf_client, client_vm, extra_options
                )
                iface = client_vm.get_ifname()
                clear_qos_setting(iface)
                results.append([iface, throughout, rate, burst])
        report_test_results(results)
    finally:
        try:
            # cleanup netperf env
            test.log.debug("Cleanup netperf env")
            for ntpf, _ in itertools.chain(netperf_clients, netperf_servers):
                ntpf.cleanup()
        except Exception as e:
            test.log.warning("Cleanup failed:\n%s\n", e)
        for f in glob.glob("/var/log/openvswith/*.log"):
            dst = os.path.join(test.resultsdir, os.path.basename(f))
            shutil.copy(f, dst)
