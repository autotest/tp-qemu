import logging
import os
import time

from virttest import error_context
from virttest import data_dir
from virttest import utils_misc
from virttest import utils_net
from virttest import utils_netperf


@error_context.context_aware
def netperf_stress(test, params, vm):
    """
    Netperf stress test.
    """
    n_client = utils_netperf.NetperfClient(
        vm.get_address(),
        params.get("client_path"),
        netperf_source=os.path.join(data_dir.get_deps_dir("netperf"),
                                    params.get("netperf_client_link")),
        client=params.get("shell_client"),
        port=params.get("shell_port"),
        username=params.get("username"),
        password=params.get("password"),
        prompt=params.get("shell_prompt"),
        linesep=params.get("shell_linesep", "\n").encode().decode(
            'unicode_escape'),
        status_test_command=params.get("status_test_command", ""),
        compile_option=params.get("compile_option", ""))
    n_server = utils_netperf.NetperfServer(
        utils_net.get_host_ip_address(params),
        params.get("server_path", "/var/tmp"),
        netperf_source=os.path.join(data_dir.get_deps_dir("netperf"),
                                    params.get("netperf_server_link")),
        password=params.get("hostpassword"),
        compile_option=params.get("compile_option", ""))

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
        n_client.bg_start(utils_net.get_host_ip_address(params),
                          t_option,
                          params.get_numeric("netperf_para_sessions"),
                          params.get("netperf_cmd_prefix", ""),
                          package_sizes=params.get("netperf_sizes"))
        if utils_misc.wait_for(n_client.is_netperf_running, 10, 0, 1,
                               "Wait netperf test start"):
            logging.info("Netperf test start successfully.")
        else:
            test.error("Can not start netperf client.")
        start_time = time.time()
        execution_time = test_duration + deviation_time
        utils_misc.wait_for(lambda: not
                            n_client.is_netperf_running(),
                            execution_time, 0, 2,
                            "Wait netperf test finish %ss" % test_duration)
        stop_time = time.time()
        run_time = stop_time - start_time
        if n_client.is_netperf_running():
            test.fail("netperf still running,netperf hangs")
        elif test_duration - 5 <= run_time:
            logging.info("netperf runs successfully")
        else:
            test.fail("netperf terminated unexpectedly,executed %ss" % run_time)
    finally:
        n_server.stop()
        n_server.cleanup(True)
        n_client.cleanup(True)
