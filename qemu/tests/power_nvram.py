import re

from virttest import error_context, qemu_monitor, virt_vm


@error_context.context_aware
def run(test, params, env):
    """
    nvram test on power:
    1) Boot vm with different raw string for nvram
    2) Qemu works as expected

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    vm = env.get_vm(params["main_vm"])
    error_msg = params.get("nvram_expected_result")
    nvram_sub_type = params.get("nvram_sub_type")
    if nvram_sub_type != "normal":
        try:
            vm.create(params=params)
        except virt_vm.VMCreateError as e:
            output = e.output
            error_context.context(
                "Check the expected error message: %s" % error_msg, test.log.info
            )
            if not re.search(error_msg, output):
                test.fail(
                    "Can not get expected error message: %s from %s"
                    % (error_msg, output)
                )
        except qemu_monitor.MonitorConnectError:
            pass
    else:
        vm.wait_for_login()
        vm.verify_kernel_crash()
