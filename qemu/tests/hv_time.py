import re

from virttest import env_process, error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Test hv_time flag avaliability and effectiveness.

    1) boot the guest, setup the testing environment
    2) reboot the guest without hv_time flag
    3) run gettime_cycles.exe to acquire cpu cycles of IO operations
    4) reboot the guest with hv_time flag
    5) run the gettime_cycles.exe again, then compare the cycles
       to previous result

    param test: the test object
    param params: the test params
    param env: the test env object
    """

    def _setup_environments():
        """
        Setup the guest test environment, includes close the useplatformclock,
        and copy gettime_cycles.exe related files to guest
        """
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        session = vm.wait_for_login(timeout=timeout)

        test.log.info("Turn off the useplatformclock attribute")
        session.cmd(close_pltclk_cmd)

        test.log.info("Reboot to check the useplatformclock is off")
        session = vm.reboot(session, timeout=timeout)
        s, o = session.cmd_status_output(check_pltclk_cmd)
        if s:
            test.error(
                "Failed to check the useplatfromclock after reboot, "
                "status=%s, output=%s" % (s, o)
            )
        use_pltck = re.search(r"useplatformclock\s+no", o, re.I | re.M)
        if not use_pltck:
            test.error("The useplatfromclock isn't off after reboot, " "output=%s" % o)

        test.log.info("Copy the related files to the guest")
        for f in gettime_filenames:
            copy_file_cmd = utils_misc.set_winutils_letter(session, copy_cmd % f)
            session.cmd(copy_file_cmd)
        vm.graceful_shutdown(timeout=timeout)

    def _run_gettime(session):
        """
        Run the gettime_cycles.exe to acquire cpu cycles

        return: the cpu cycles amount of certain IO operation
        """
        o = session.cmd_output_safe(run_gettime_cmd, timeout=timeout)
        cycles = int(re.search(r"\d+", o).group(0))
        test.log.info("The cycles with out hv_time is %d", cycles)
        return cycles

    def _boot_guest_with_cpu_flag(hv_flag):
        """
        Boot the guest, with param cpu_model_flags set to hv_flag

        param hv_flag: the hv flags to set to cpu

        return: the booted vm
        """
        params["cpu_model_flags"] = hv_flag
        params["start_vm"] = "yes"
        vm_name = params["main_vm"]
        env_process.preprocess(test, params, env)
        return env.get_vm(vm_name)

    def _get_cycles_with_flags(cpu_flag):
        """
        Boot the guest with cpu_model_flags set to cpu_flag,
        then run gettime_cycle.exe to acquire cpu cycles.

        param cpu_flag: the cpu flags to set
        return: the cpu cycles returned by gettime_cycle.exe
        """
        test.log.info("Boot the guest with cpu_model_flags= %s", cpu_flag)
        vm = _boot_guest_with_cpu_flag(cpu_flag)
        session = vm.wait_for_login(timeout=timeout)
        test.log.info("Run gettime_cycle.exe")
        cycles = _run_gettime(session)
        vm = env.get_vm(params["main_vm"])
        vm.graceful_shutdown(timeout=timeout)
        return cycles

    def _check_result(cycles_without_flag, cycles_with_flag):
        """
        Calculate the factor of optimization for the hv_time flag usage,
        and check if the factor is as effective as we want.
        param cycles_without_flag: the cpu cycles acquired by
            gettime_cycles.exe, without hv_time flag set
        param cycles_with_flag: the cpu cycles acquired by gettime_cycles.exe,
            with hv_time flag set
        """
        factor = cycles_with_flag / float(cycles_without_flag)
        if factor > 0.1:
            test.fail(
                "Cycles with flag is %d, cycles without flag is %d, "
                "the factor is %f > 0.1"
                % (cycles_with_flag, cycles_without_flag, factor)
            )

    close_pltclk_cmd = params["close_pltclk_cmd"]
    check_pltclk_cmd = params["check_pltclk_cmd"]
    gettime_filenames = params["gettime_filenames"].split()
    copy_cmd = params["copy_cmd"]
    run_gettime_cmd = params["run_gettime_cmd"]
    timeout = params.get("timeout", 360)
    hv_time_flags = params["hv_time_flags"].split()
    flags_with_hv_time = params["cpu_model_flags"]
    flags_without_hv_time = ",".join(
        [_ for _ in flags_with_hv_time.split(",") if _ not in hv_time_flags]
    )

    error_context.context("Setting up environments", test.log.info)
    _setup_environments()

    error_context.context("Get cpu cycles without hv_time flag", test.log.info)
    cycles_without_flag = _get_cycles_with_flags(flags_without_hv_time)

    error_context.context("Get cpu cycles with hv_time flag", test.log.info)
    cycles_with_flag = _get_cycles_with_flags(flags_with_hv_time)

    error_context.context("Check the optimize factor", test.log.info)
    _check_result(cycles_without_flag, cycles_with_flag)
