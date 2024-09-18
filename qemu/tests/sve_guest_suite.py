import re

from virttest import error_context, utils_package

from provider import cpu_utils


@error_context.context_aware
def run(test, params, env):
    def get_sve_supports_lengths():
        """
        Get supported SVE lengths of host.
        """
        output = vm.monitor.query_cpu_model_expansion(vm.cpuinfo.model)
        output.pop("sve")
        sve_list = [
            sve for sve in output if output[sve] is True and sve.startswith("sve")
        ]
        sve_list.sort(key=lambda x: int(x[3:]))
        return sve_list

    def compile_test_suite():
        session.cmd(get_suite_cmd, timeout=180)
        if suite_type == "sve_stress":
            session.cmd(params["uncompress_cmd"].format(tmp_dir, linux_name))
        error_context.context("Compile the test suite......", test.log.info)
        s, o = session.cmd_status_output(compile_cmd, timeout=180)
        if s:
            test.log.error("Compile output: %s", o)
            test.error("Failed to compile the test suite.")

    def sve_stress():
        s, o = session.cmd_status_output(f"{suite_dir}/sve-probe-vls")
        test_lengths = re.findall(r"# (\d+)$", o, re.M)
        if s or not test_lengths:
            test.error('Could not get supported SVE lengths by "sve-probe-vls"')
        test.log.info("The lengths of SVE used for testing are: %s", test_lengths)
        for sve_length in test_lengths:
            out = session.cmd_output(
                execute_suite_cmd.format(sve_length), timeout=(suite_timeout + 10)
            )
            results_lines = [
                result
                for result in out.splitlines()
                if result.startswith("Terminated by")
            ]
            if len(re.findall(r"no error", out, re.M)) != len(results_lines):
                test.log.debug("Test results: %s", results_lines)
                test.fail("SVE stress test failed")

    def optimized_routines():
        out = session.cmd_output(execute_suite_cmd, timeout=suite_timeout)
        results = re.findall(r"^(\w+) \w+sve$", out, re.M)
        if not all([result == "PASS" for result in results]):
            test.log.debug("Test results: %s", results)
            test.fail("optimized routines suite test failed")

    cpu_utils.check_cpu_flags(params, "sve", test)
    vm = env.get_vm(params["main_vm"])
    sve_lengths = get_sve_supports_lengths()
    vm.destroy()

    compile_cmd = params["compile_cmd"]
    dst_dir = params["dst_dir"]
    execute_suite_cmd = params["execute_suite_cmd"]
    get_suite_cmd = params["get_suite_cmd"]
    suite_dir = params["suite_dir"]
    suite_timeout = params.get_numeric("suite_timeout")
    suite_type = params["suite_type"]
    required_pkgs = params.objects("required_pkgs")
    tmp_dir = params["tmp_dir"]

    error_context.context("Launch a guest with sve=on", test.log.info)
    sve_opts = ("{}={}".format(sve, "on") for sve in sve_lengths)
    params["cpu_model_flags"] = "sve=on," + ",".join(sve_opts)
    vm.create(params=params)
    vm.verify_alive()
    session = vm.wait_for_login()
    cpu_utils.check_cpu_flags(params, "sve", test, session)

    kernel_version = session.cmd_output("uname -r").rsplit(".", 1)[0]
    srpm = f"kernel-{kernel_version}.src.rpm"
    linux_name = f"linux-{kernel_version}"
    get_suite_cmd = get_suite_cmd.format(tmp_dir, srpm)
    session.cmd(f"mkdir {dst_dir}")

    if not utils_package.package_install(required_pkgs, session):
        test.error("Failed to install required packages in guest")
    compile_test_suite()
    error_context.context("Execute the test suite......", test.log.info)
    locals()[suite_type]()
