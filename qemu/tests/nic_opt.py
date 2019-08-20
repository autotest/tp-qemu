import logging
import os
import time

from avocado.utils import cpu
from virttest import data_dir
from virttest import error_context
from virttest import utils_misc
from virttest import utils_net
from virttest import utils_netperf
from virttest import utils_test


@error_context.context_aware
def run(test, params, env):
    """
    NIC option check test.
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def test_netperf():
        """
        Netperf stress test for nic option.
        """
        netperf_client_link = os.path.join(data_dir.get_deps_dir("netperf"),
                                           params.get("netperf_client_link"))
        client_path = params.get("client_path")

        n_client = utils_netperf.NetperfClient(vm.get_address(), client_path,
                                               netperf_source=netperf_client_link, client=params.get("shell_client"),
                                               port=params.get("shell_port"), username=params.get("username"),
                                               password=params.get("password"), prompt=params.get("shell_prompt"),
                                               linesep=params.get("shell_linesep", "\n").encode().decode(
                                                   'unicode_escape'),
                                               status_test_command=params.get("status_test_command", ""))

        n_server = utils_netperf.NetperfServer(utils_net.get_host_ip_address(params),
                                               params.get("server_path", "/var/tmp"),
                                               netperf_source=os.path.join(data_dir.get_deps_dir("netperf"),
                                                                           params.get("netperf_server_link")),
                                               password=params.get("hostpassword"))

        try:
            n_server.start()
            # Run netperf with message size defined in range.
            netperf_test_duration = int(params.get("netperf_test_duration", 180))
            netperf_para_sess = params.get("netperf_para_sessions", "1")
            test_protocols = params.get("test_protocols", "TCP_STREAM")
            netperf_cmd_prefix = params.get("netperf_cmd_prefix", "")
            netperf_output_unit = params.get("netperf_output_unit")
            netperf_package_sizes = params.get("netperf_sizes")
            test_option = params.get("test_option", "")
            test_option += " -l %s" % netperf_test_duration
            if params.get("netperf_remote_cpu") == "yes":
                test_option += " -C"
            if params.get("netperf_local_cpu") == "yes":
                test_option += " -c"
            if netperf_output_unit in "GMKgmk":
                test_option += " -f %s" % netperf_output_unit
            start_time = time.time()
            stop_time = start_time + netperf_test_duration
            num = 0
            for protocol in test_protocols.split():
                error_context.context("Testing %s protocol" % protocol,
                                      logging.info)
                t_option = "%s -t %s" % (test_option, protocol)
                n_client.bg_start(utils_net.get_host_ip_address(params), t_option,
                                  netperf_para_sess, netperf_cmd_prefix,
                                  package_sizes=netperf_package_sizes)
                if utils_misc.wait_for(n_client.is_netperf_running, 10, 0, 1,
                                       "Wait netperf test start"):
                    logging.info("Netperf test start successfully.")
                else:
                    test.error("Can not start netperf client.")
                num += 1
                # here when set a run flag, when other case call this case as a
                # subprocess backgroundly,can set this run flag to False to stop
                # the stress test.
                env["netperf_run"] = True

                netperf_test_duration = stop_time - time.time()
                utils_misc.wait_for(
                    lambda: not n_client.is_netperf_running(),
                    netperf_test_duration, 0, 5,
                    "Wait netperf test finish %ss" % netperf_test_duration)
                time.sleep(5)
        finally:
            n_server.stop()
            n_server.package.env_cleanup(True)
            n_client.package.env_cleanup(True)

    def test_ping():
        """
        Ping test for nic option.
        """
        package_sizes = params.objects("ping_sizes")
        if params["os_type"] == "windows":
            ifname = utils_net.get_windows_nic_attribute(
                session=session,
                key="netenabled",
                value=True,
                target="netconnectionID")
        else:
            ifname = utils_net.get_linux_ifname(session,
                                                vm.get_mac_address())
        dest = utils_net.get_host_ip_address(params)

        for size in package_sizes:
            error_context.context("Test ping from '%s' to host '%s' on guest '%s'"
                                  " with package size %s. " %
                                  (ifname, dest, vm.name, size), logging.info)
            status, output = utils_net.ping(dest=dest, count=10, packetsize=size, session=session, timeout=30)
            if status:
                test.fail("%s ping %s unexpected, output %s" % (vm.name, dest,
                                                                output))
            if params["os_type"] == "windows":
                # windows guest get loss=0 when ping failed sometime,
                # need further check
                loss = utils_test.get_loss_ratio(output)
                if loss or "TTL" in output:
                    pass
                else:
                    test.fail("Guest ping test hit unexpected loss, "
                              "error_info: %s" % output)

    check_type = params.get("check_type")
    smp_value = params.get_numeric("smp") or params.get_numeric("vcpu_maxcpus")
    if cpu.online_cpus_count() < 2 * smp_value:
        test.cancel("The number of smp counts in this host is not big enough")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_serial_login()
    try:
        if params["os_type"] == "windows":
            error_context.context("Verify if netkvm.sys is enabled in guest",
                                  logging.info)
            session = utils_test.qemu.windrv_check_running_verifier(session, vm,
                                                                    test, "netkvm")
        func_name = {"ping": test_ping, "netperf": test_netperf}
        func_name[check_type]()
    finally:
        session.close()
