import re
import time

from virttest import env_process, error_context, utils_misc, utils_test
from virttest.utils_test import BackgroundTest

from provider.cpu_utils import check_cpu_flags


@error_context.context_aware
def run(test, params, env):
    """
    smt test:
    1) Check if host has topoext flag, if not, cancel test
    2) Boot guest and check cpu count and threads number in guest
    3) Run stress inside guest, and check cpu usage in guest(only for linux)

    :params test: QEMU test object.
    :params params: Dictionary with the test parameters.
    :params env: Dictionary with test environment.
    """

    def run_guest_cmd(cmd, retry=False):
        """
        Run cmd inside guest
        """
        output = session.cmd_output_safe(cmd)
        if retry and not output:
            output = session.cmd_output_safe(cmd)
        if not output:
            test.error("Get empty output after run cmd %s" % cmd)
        return output

    def get_guest_threads():
        """
        Get guest threads number
        """
        if os_type == "linux":
            cmd = params["get_threads_cmd"]
            output = run_guest_cmd(cmd)
            threads = int(re.findall(r":\s*(\d+)", output)[0])
        else:
            cmd = params["get_cores_cmd"]
            output = run_guest_cmd(cmd, retry=True)
            cores = int(re.findall(r"=(\d+)", output)[0])
            cmd = params["get_sockets_cmd"]
            output = run_guest_cmd(cmd)
            sockets = len(re.findall(r"SocketDesignation=", output))
            threads = int(vm.cpuinfo.smp / sockets / cores)
        return threads

    def heavyload_install(install_path):
        """
        Install heavyload in windows guest
        """
        test_installed_cmd = 'dir "%s" | findstr /I heavyload' % install_path
        if session.cmd_status(test_installed_cmd) != 0:
            test.log.warning(
                "Could not find installed heavyload in guest, will"
                " install it via winutils.iso "
            )
            winutil_drive = utils_misc.get_winutils_vol(session)
            if not winutil_drive:
                test.cancel("WIN_UTILS CDROM not found.")
            install_cmd = params["install_cmd"] % winutil_drive
            session.cmd(install_cmd)

    def run_stress():
        """
        Run stress inside guest, return guest cpu usage
        """
        error_context.context("Run stress in guest and get cpu usage", test.log.info)
        if os_type == "linux":
            stress_args = params["stress_args"]
            stress_test = utils_test.VMStress(
                vm, "stress", params, stress_args=stress_args
            )
            try:
                stress_test.load_stress_tool()
                time.sleep(stress_duration / 2)
                output = session.cmd_output_safe(params["get_cpu_usage_cmd"])
                utils_misc.wait_for(lambda: (stress_test.app_running is False), 30)
                stress_test.unload_stress()
                cpu_usage = re.findall(r":\s*(\d+.?\d+)\s*us", output)
                cpu_usage = [float(x) for x in cpu_usage]
                test.log.info("Guest cpu usage is %s", cpu_usage)
                unloaded_cpu = [x for x in cpu_usage if x < 20]
                if unloaded_cpu:
                    test.fail("CPU(s) load percentage is less than 20%")
            finally:
                stress_test.clean()
        else:
            install_path = params["install_path"]
            heavyload_install(install_path)
            error_context.context("Run heavyload inside guest.", test.log.info)
            heavyload_bin = r'"%s\heavyload.exe" ' % install_path
            heavyload_options = [
                "/CPU %d" % vm.cpuinfo.smp,
                "/DURATION %d" % (stress_duration // 60),
                "/AUTOEXIT",
                "/START",
            ]
            start_cmd = heavyload_bin + " ".join(heavyload_options)
            stress_tool = BackgroundTest(
                session.cmd, (start_cmd, stress_duration, stress_duration)
            )
            stress_tool.start()
            if not utils_misc.wait_for(stress_tool.is_alive, stress_duration):
                test.error("Failed to start heavyload process.")
            stress_tool.join(stress_duration)

    check_cpu_flags(params, "topoext", test)
    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])

    os_type = params["os_type"]
    stress_duration = params.get_numeric("stress_duration", 60)
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    try:
        if vm.get_cpu_count() != vm.cpuinfo.smp:
            test.fail("Guest cpu number is not right")
        threads = get_guest_threads()
        test.log.info("Guest threads number is %s", threads)
        if threads != params.get_numeric("expected_threads", 1):
            test.fail("Guest cpu threads number is not right")
        run_stress()
    finally:
        if session:
            session.close()
