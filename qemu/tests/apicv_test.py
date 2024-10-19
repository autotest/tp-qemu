import os
import re
import time

from avocado.utils import process
from virttest import data_dir, env_process, error_context, utils_net, utils_netperf


@error_context.context_aware
def run(test, params, env):
    """
    apicv test:
    1) Check if apicv is enabled on host, if not, enable it
    2) Boot guest and run netperf inside guest
    3) Record throughput and shutdown guest
    4) Disable apicv on host
    5) Boot guest and run netperf inside guest again
    6) Compare benchmark scores with step 3)
    7) Restore env, set apicv back

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def reload_module(value):
        """
        Reload module
        """
        process.system("rmmod %s" % module)
        cmd = "modprobe %s %s=%s" % (module, mod_param, value)
        process.system(cmd)

    def run_netperf():
        """
        Run netperf test, return average throughput
        """
        error_context.context("Run netperf test", test.log.info)
        n_server.start()
        n_client.session = session
        throughput = 0
        for i in range(repeat_times):
            output = n_client.start(
                server_address=host_ip, test_option=params.get("test_option")
            )
            throughput += float(re.findall(r"580\s+\d+\.?\d+\s+(\d+\.?\d+)", output)[0])
            time.sleep(1)
        n_server.stop()
        return throughput / repeat_times

    module = params["module_name"]
    mod_param = params["mod_param"]
    error_context.context("Enable apicv on host", test.log.info)
    cmd = "cat /sys/module/%s/parameters/%s" % (module, mod_param)
    ori_apicv = process.getoutput(cmd)
    if ori_apicv != "Y":
        reload_module("Y")

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    host_ip = utils_net.get_host_ip_address(params)
    n_server = utils_netperf.NetperfServer(
        address=host_ip,
        netperf_path=params["server_path"],
        netperf_source=os.path.join(
            data_dir.get_deps_dir("netperf"), params.get("netperf_server_link")
        ),
        username=params.get("host_username", "root"),
        password=params.get("host_password"),
    )

    n_client = utils_netperf.NetperfClient(
        address=vm.get_address(),
        netperf_path=params["client_path"],
        netperf_source=os.path.join(
            data_dir.get_deps_dir("netperf"), params.get("netperf_client_link")
        ),
        client=params.get("shell_client", "ssh"),
        port=params.get("shell_port"),
        username=params.get("username"),
        password=params.get("password"),
        prompt=params.get("shell_prompt", r"^root@.*[\#\$]\s*$|#"),
    )

    repeat_times = params.get_numeric("repeat_times", 10)
    try:
        value_on = run_netperf()
        test.log.info("When enable apicv, average throughput is %s", value_on)
        vm.destroy()

        error_context.context("Disable apicv on host", test.log.info)
        reload_module("N")
        vm.create(params=params)
        session = vm.wait_for_login()
        value_off = run_netperf()
        test.log.info("When disable apicv, average throughput is %s", value_off)
        threshold = float(params.get("threshold", 0.9))
        if value_on <= value_off * threshold:
            test.fail("Throughput is smaller when apicv is on than off")
    finally:
        n_server.cleanup(True)
        n_client.cleanup(True)
        session.close()
        vm.destroy()
        reload_module(ori_apicv)
