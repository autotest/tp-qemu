import logging
import os
import time

from virttest import data_dir, error_context, utils_misc, utils_net, utils_netperf

LOG_JOB = logging.getLogger("avocado.test")


@error_context.context_aware
def netperf_stress(test, params, vm):
    """
    Netperf stress test.
    """
    n_client = utils_netperf.NetperfClient(
        vm.get_address(),
        params.get("client_path"),
        netperf_source=os.path.join(
            data_dir.get_deps_dir("netperf"), params.get("netperf_client_link")
        ),
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
        test_duration = params.get_numeric("netperf_test_duration")
        deviation_time = params.get_numeric("deviation_time")
        test_protocols = params.get("test_protocol")
        netperf_output_unit = params.get("netperf_output_unit")
        test_option = params.get("test_option", "")
        test_option += " -l %s" % test_duration
        if params.get("netperf_remote_cpu") == "yes":
            test_option += " -C"
        if params.get("netperf_local_cpu") == "yes":
            test_option += " -c"
        if netperf_output_unit in "GMKgmk":
            test_option += " -f %s" % netperf_output_unit
        t_option = "%s -t %s" % (test_option, test_protocols)
        n_client.bg_start(
            utils_net.get_host_ip_address(params),
            t_option,
            params.get_numeric("netperf_para_sessions"),
            params.get("netperf_cmd_prefix", ""),
            package_sizes=params.get("netperf_sizes"),
        )
        if utils_misc.wait_for(
            n_client.is_netperf_running, 10, 0, 3, "Wait netperf test start"
        ):
            LOG_JOB.info("Netperf test start successfully.")
        else:
            test.error("Can not start netperf client.")
        start_time = time.time()
        duration = time.time() - start_time
        max_run_time = test_duration + deviation_time
        while duration < max_run_time:
            time.sleep(10)
            duration = time.time() - start_time
            status = n_client.is_netperf_running()
            if not status and duration < test_duration - 10:
                test.fail("netperf terminated unexpectedly")
            LOG_JOB.info("Wait netperf test finish %ss", duration)
        if n_client.is_netperf_running():
            test.fail("netperf still running, netperf hangs")
        else:
            LOG_JOB.info("netperf runs successfully")
    finally:
        n_server.stop()
        n_server.cleanup(True)
        n_client.cleanup(True)
