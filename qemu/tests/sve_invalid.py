import re

from avocado.utils import cpu
from virttest import error_context
from virttest.virt_vm import VMCreateError


@error_context.context_aware
def run(test, params, env):
    def get_sve_lengths(supported=True):
        """
        Get unsupported SVE lengths of host.
        """
        output = vm.monitor.query_cpu_model_expansion(vm.cpuinfo.model)
        output.pop("sve")
        sve_list = [
            sve for sve in output if output[sve] is supported and sve.startswith("sve")
        ]
        sve_list.sort(key=lambda x: int(x[3:]))

        return sve_list

    error_msg = params["error_msg"]
    invalid_length = params.get("invalid_length")
    invalid_type = params.get("sve_invalid")

    vm = env.get_vm(params["main_vm"])
    sve_flag = cpu.cpu_has_flags("sve")
    if invalid_type != "non_sve_host":
        if not sve_flag:
            test.cancel("The host doesn't support SVE feature")
        if not invalid_length:
            active_length = params.get_boolean("active_length")
            sve_lengths = get_sve_lengths(active_length)
            if active_length:
                if len(sve_lengths) == 1:
                    test.cancel("The host only supports one sve length")
                disabled_length = sve_lengths[-2]
                flags = (
                    "{}={}".format(sve, "on" if sve != disabled_length else "off")
                    for sve in sve_lengths
                )
                flags = ",".join(flags)
                error_msg = error_msg.format(sve_lengths[-1][3:])
            else:
                invalid_length = sve_lengths[-1]
                error_msg = error_msg.format(invalid_length[3:])
                flags = "{}=on".format(invalid_length)
            vm.destroy()
            params["cpu_model_flags"] = "sve=on," + flags
    else:
        if sve_flag:
            test.cancel("The host supports SVE feature, cancel the test...")
        params["cpu_model_flags"] = "sve=on"

    params["start_vm"] = "yes"
    try:
        error_context.context("Launch a guest with invalid SVE scenario", test.log.info)
        vm.create(params=params)
    except VMCreateError as err:
        if not re.search(error_msg, err.output, re.M):
            test.error(
                "The guest failed to be launched but did not get the "
                "expected error message."
            )
        test.log.info("The qemu process terminated as expected.")
    else:
        test.fail("The guest should not be launched.")
