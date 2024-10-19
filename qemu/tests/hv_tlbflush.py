import datetime
import os
import time

from avocado.utils import cpu
from virttest import (
    data_dir,
    env_process,
    error_context,
    utils_misc,
    utils_numeric,
    utils_test,
)


@error_context.context_aware
def run(test, params, env):
    """
    Test hv_tlbflush flag improvement
    1) Prepare test related tools on host and guest, includes
       hv_tlbflush.exe and related files, and stress tool
    2) Boot the guest without hv_tlbflush and other related flags
    3) Run stress tool on host, then run hv_tlbflush.exe on guest,
       the total running time is acquired
    4) Shutdown and reboot guest with all hv flags
    5) Run stress tool and hv_tlvflush.exe again on host&guest,
       another time is acquired
    6) Compare the 2 time and calculate the improvement factor,
       then judge the result depends on the architecure of the guest

    param test: the test object
    param params: the test params
    param env: the test env object
    """

    def _prepare_test_environment():
        """
        Prepare the test tools, such as hv_tlbflush & stress

        return: a running HostStress object
        """

        copy_tlbflush_cmd = params["copy_tlbflush_cmd"]

        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)

        test.log.info("Copy tlbflush tool related files")
        for f in tlbflush_filenames:
            copy_file_cmd = utils_misc.set_winutils_letter(
                session, copy_tlbflush_cmd % f
            )
            session.cmd(copy_file_cmd)

        test.log.info("Create a large file for test")
        create_test_file_cmd = params["create_test_file_cmd"]
        test_file_size = params["test_file_size"]
        test_file_size = utils_numeric.normalize_data_size(
            test_file_size, order_magnitude="B"
        )
        session.cmd(create_test_file_cmd % test_file_size)
        vm.graceful_shutdown(timeout=timeout)

        stress_type = params.get("stress_type", "stress")
        stress_pkg_name = params.get("stress_pkg_name", "stress-1.0.4.tar.gz")
        stress_root_dir = data_dir.get_deps_dir("stress")
        downloaded_file_path = os.path.join(stress_root_dir, stress_pkg_name)
        host_cpu_count = cpu.total_cpus_count()

        host_stress = utils_test.HostStress(
            stress_type,
            params,
            download_type="tarball",
            downloaded_file_path=downloaded_file_path,
            stress_args="--cpu %s > /dev/null 2>&1& " % host_cpu_count,
        )
        return host_stress

    def _clean_test_environment(host_stress):
        """
        Remove the test related files

        param host_stress: the HostStress object
        """
        delete_tlbflush_cmd = params["delete_tlbflush_cmd"]
        delete_test_file_cmd = params["delete_test_file_cmd"]

        _stop_host_stress(host_stress)
        test.log.info("Cleanup the stress tool on host")
        host_stress.clean()

        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()

        session = vm.wait_for_login(timeout=timeout)
        test.log.info("Delete tlbflush files")
        for f in tlbflush_filenames:
            session.cmd(delete_tlbflush_cmd % f)

        test.log.info("Delete test file")
        session.cmd(delete_test_file_cmd)

    def _start_host_stress(host_stress):
        """
        Start running stress tool on host

        param host_stress: the HostStress object
        """
        if not host_stress.app_running():
            host_stress.load_stress_tool()

        if not host_stress.app_running():
            test.error("Can't start the stress tool on host")

    def _stop_host_stress(host_stress):
        """
        Stop the stress tool on host

        param host_stress: the running HostStress object
        """
        if host_stress.app_running():
            host_stress.unload_stress()

    def _boot_guest_with_cpu_flag(hv_flag):
        """
        Boot the guest, with param cpu_model_flags set to hv_flag

        param hv_flag: the hv flags to set to cpu

        return: the booted vm and a loggined session
        """
        params["cpu_model_flags"] = hv_flag
        params["start_vm"] = "yes"
        vm_name = params["main_vm"]
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        session = vm.wait_for_login(timeout=timeout)
        return (vm, session)

    def _run_tlbflush(session, host_stress):
        """
        Start running the hv_tlvflush tool on guest.

        param session: a loggined session to send commands

        return: the time result of the running, a float value
        """
        run_tlbflush_cmd = params["run_tlbflush_cmd"]
        run_tlbflush_timeout = params.get_numeric("run_tlbflush_timeout", 3600)

        test.log.info("Start stress on host")
        _start_host_stress(host_stress)

        test.log.info("Start run hv_tlbflush.exe on guest")
        s, o = session.cmd_status_output(run_tlbflush_cmd, run_tlbflush_timeout)
        test.log.info("Stop stress on host")
        _stop_host_stress(host_stress)

        if s:
            test.error("Run tlbflush error: status = %s, output = %s", (s, o))
        time_str = o.strip().split("\n")[-1]
        time_str = time_str.split(".")[0]
        s_t = time.strptime(time_str, "%H:%M:%S")
        total_time = datetime.timedelta(
            hours=s_t.tm_hour, minutes=s_t.tm_min, seconds=s_t.tm_sec
        ).total_seconds()
        test.log.info("Running result: %f", total_time)
        return total_time

    timeout = params.get_numeric("timeout", 360)
    tlbflush_filenames = params["tlbflush_filenames"].split()
    cpu_model_flags = params["cpu_model_flags"]
    hv_flags_to_ignore = params["hv_flags_to_ignore"].split()

    error_context.context("Prepare test environment", test.log.info)
    host_stress = _prepare_test_environment()

    try:
        error_context.context("Boot guest with hv_tlbflush related flags")
        hv_flag_without_tlbflush = ",".join(
            [_ for _ in cpu_model_flags.split(",") if _ not in hv_flags_to_ignore]
        )
        vm, session = _boot_guest_with_cpu_flag(hv_flag_without_tlbflush)

        error_context.context("Run tlbflush without hv_tlbflush", test.log.info)
        time_without_flag = _run_tlbflush(session, host_stress)
        vm.graceful_shutdown(timeout=timeout)

        error_context.context("Boot guest with related flags")
        vm, session = _boot_guest_with_cpu_flag(cpu_model_flags)
        error_context.context("Run tlbflush with hv_tlbflush", test.log.info)
        time_with_flag = _run_tlbflush(session, host_stress)

        error_context.context("Compare test results between 2 tests")
        factor = time_with_flag / time_without_flag
        vm_arch = params.get("vm_arch_name")
        if factor >= 0.5 if vm_arch == "x86_64" else factor >= 1.0:
            test.fail(
                "The improvement factor=%d is not enough. "
                "Time WITHOUT flag: %s, "
                "Time WITH flag: %s" % (factor, time_without_flag, time_with_flag)
            )

    finally:
        _clean_test_environment(host_stress)
