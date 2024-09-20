import re

from virttest import error_context

from provider import cpu_utils


@error_context.context_aware
def run(test, params, env):
    def get_sve_supported_lengths():
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

    def launch_sve_guest(sve_opts, check_length):
        """
        Launch a guest with the given SVE options.

        :param sve_opts: List of SVE options to be used.
        :param check_length: SVE length to be checked in dmesg.
        """
        test.log.info("Launch a guest with %s", sve_opts)
        params["cpu_model_flags"] = "sve=on," + ",".join(sve_opts)
        vm.create(params=params)
        vm.verify_alive()
        session = vm.wait_for_login()
        sve_output = session.cmd_output("dmesg | grep SVE").strip()
        if re.findall(
            "vector length {} bytes".format(check_length * 8), sve_output, re.M
        ):
            test.fail("SVE length is incorrect, output:\n{}".format(sve_output))
        session.close()
        vm.destroy()

    cpu_utils.check_cpu_flags(params, "sve", test)
    vm = env.get_vm(params["main_vm"])
    sve_lengths = get_sve_supported_lengths()
    vm.destroy()

    error_context.context("Launch a guest with sve=on", test.log.info)
    for length in sve_lengths:
        opts = (
            "{}={}".format(
                sve,
                "on" if sve_lengths.index(sve) <= sve_lengths.index(length) else "off",
            )
            for sve in sve_lengths
        )
        launch_sve_guest(opts, length)

    error_context.context("Launch a guest with sve=off", test.log.info)
    opts = ("{}={}".format(sve, "off") for sve in sve_lengths)
    params["cpu_model_flags"] = "sve=off," + ",".join(opts)
    vm.create(params=params)
    vm.verify_alive()
    session = vm.wait_for_login()
    if session.cmd_output("dmesg | grep SVE"):
        test.fail("The guest gets the SVE feature without using SVE to start")
