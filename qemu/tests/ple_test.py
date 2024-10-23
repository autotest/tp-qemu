import re

from avocado.utils import cpu, process
from virttest import env_process, error_context, utils_package


@error_context.context_aware
def run(test, params, env):
    """
    ple test:
    1) Check if ple is enabled on host, if not, enable it
    2) Boot guest and run unixbench inside guest
    3) Record benchmark scores and shutdown guest
    4) Disable ple on host
    5) Boot guest and run unixbench inside guest again
    6) Compare benchmark scores with step 3)
    7) Restore env, set ple back

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

    def run_unixbench(cmd):
        """
        Run unixbench inside guest, return benchmark scores
        """
        error_context.context("Run unixbench inside guest", test.log.info)
        output = session.cmd_output_safe(cmd, timeout=4800)
        scores = re.findall(r"System Benchmarks Index Score\s+(\d+\.?\d+)", output)
        return [float(i) for i in scores]

    module = params["module_name"]
    mod_param = params["mod_param"]
    read_cmd = "cat /sys/module/%s/parameters/%s" % (module, mod_param)
    origin_ple = process.getoutput(read_cmd)
    error_context.context("Enable ple on host if it's disabled", test.log.info)
    if origin_ple == 0:
        reload_module(params["ple_value"])

    host_cpu_count = cpu.online_count()
    params["smp"] = host_cpu_count
    params["vcpu_maxcpus"] = host_cpu_count
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    try:
        pkgs = params.objects("depends_pkgs")
        if not utils_package.package_install(pkgs, session):
            test.error("Install dependency packages failed")
        session.cmd(params["get_unixbench"])
        cmd = params["run_unixbench"]
        scores_on = run_unixbench(cmd)
        test.log.info("Unixbench scores are %s when ple is on", scores_on)
        vm.destroy()

        error_context.context("Disable ple on host", test.log.info)
        reload_module(0)
        vm.create(params=params)
        session = vm.wait_for_login()
        scores_off = run_unixbench(cmd)
        test.log.info("Unixbench scores are %s when ple is off", scores_off)
        scores_off = [x * 0.96 for x in scores_off]
        if scores_on[0] < scores_off[0] or scores_on[1] < scores_off[1]:
            test.fail("Scores is much lower when ple is on than off")
    finally:
        session.cmd_output_safe("rm -rf %s" % params["unixbench_dir"])
        session.close()
        vm.destroy()
        reload_module(origin_ple)
