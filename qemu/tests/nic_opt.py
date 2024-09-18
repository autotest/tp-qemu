import os
import time

from avocado.utils import cpu
from virttest import (
    data_dir,
    error_context,
    utils_misc,
    utils_net,
    utils_netperf,
    utils_test,
)


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
        netperf_client_link = os.path.join(
            data_dir.get_deps_dir("netperf"), params.get("netperf_client_link")
        )
        client_path = params.get("client_path")

        n_client = utils_netperf.NetperfClient(
            vm.get_address(),
            client_path,
            netperf_source=netperf_client_link,
            client=params.get("shell_client"),
            port=params.get("shell_port"),
            username=params.get("username"),
            password=params.get("password"),
            prompt=params.get("shell_prompt"),
            linesep=params.get("shell_linesep", "\n").encode().decode("unicode_escape"),
            status_test_command=params.get("status_test_command", ""),
            compile_option=params.get("compile_option", ""),
        )

        n_server = utils_netperf.NetperfServer(
            utils_net.get_host_ip_address(params),
            params.get("server_path", "/var/tmp"),
            netperf_source=os.path.join(
                data_dir.get_deps_dir("netperf"), params.get("netperf_server_link")
            ),
            password=params.get("hostpassword"),
            compile_option=params.get("compile_option", ""),
        )

        try:
            n_server.start()
            # Run netperf with message size defined in range.
            test_duration = int(params.get("netperf_test_duration", 180))
            deviation_time = params.get_numeric("deviation_time")
            netperf_para_sess = params.get("netperf_para_sessions", "1")
            test_protocols = params.get("test_protocols", "TCP_STREAM")
            netperf_cmd_prefix = params.get("netperf_cmd_prefix", "")
            netperf_output_unit = params.get("netperf_output_unit")
            netperf_package_sizes = params.get("netperf_sizes")
            test_option = params.get("test_option", "")
            test_option += " -l %s" % test_duration
            if params.get("netperf_remote_cpu") == "yes":
                test_option += " -C"
            if params.get("netperf_local_cpu") == "yes":
                test_option += " -c"
            if netperf_output_unit in "GMKgmk":
                test_option += " -f %s" % netperf_output_unit
            num = 0
            for protocol in test_protocols.split():
                error_context.context("Testing %s protocol" % protocol, test.log.info)
                t_option = "%s -t %s" % (test_option, protocol)
                n_client.bg_start(
                    utils_net.get_host_ip_address(params),
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
                # subprocess backgroundly,can set this run flag to False to stop
                # the stress test.
                env["netperf_run"] = True
                duration = time.time() - start_time
                max_run_time = test_duration + deviation_time
                while duration < max_run_time:
                    time.sleep(10)
                    duration = time.time() - start_time
                    status = n_client.is_netperf_running()
                    if not status and duration < test_duration - 10:
                        test.fail("netperf terminated unexpectedly")
                    test.log.info("Wait netperf test finish %ss", duration)
                if n_client.is_netperf_running():
                    test.fail("netperf still running, netperf hangs")
                else:
                    test.log.info("netperf runs successfully")
        finally:
            n_server.stop()
            n_server.cleanup(True)
            n_client.cleanup(True)

    def test_ping():
        """
        Ping test for nic option.
        """
        package_sizes = params.objects("ping_sizes")
        guest_ip = vm.get_address()

        for size in package_sizes:
            error_context.context(
                "From host ping to '%s' with guest '%s'"
                " with package size %s. " % (vm.name, guest_ip, size),
                test.log.info,
            )
            status, output = utils_net.ping(
                guest_ip, count=10, packetsize=size, timeout=30
            )
            if status != 0:
                test.fail("host ping %s unexpected, output %s" % (guest_ip, output))

    check_type = params.get("check_type")
    smp_value = params.get_numeric("smp") or params.get_numeric("vcpu_maxcpus")
    if cpu.online_count() < 2 * smp_value:
        test.cancel("The number of smp counts in this host is not big enough")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_serial_login()
    try:
        match_string = "unable to start vhost net"
        output = vm.process.get_output()
        if match_string in output:
            test.fail("Qemu output error info: %s" % output)
        if params["os_type"] == "windows":
            driver_verifier = params["driver_verifier"]
            error_context.context(
                "Verify if netkvm.sys is enabled in guest", test.log.info
            )
            session = utils_test.qemu.windrv_check_running_verifier(
                session, vm, test, driver_verifier
            )
        func_name = {"ping": test_ping, "netperf": test_netperf}
        func_name[check_type]()
    finally:
        session.close()
