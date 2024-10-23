from virttest import error_context

from provider import qemu_img_utils


@error_context.context_aware
def run(test, params, env):
    """
    Add 'hv-enforce-cpuid' option to see
        whether guest use features we didn't advertize to it.
    1. Boot the guest with random set of hv flags along
        with 'hv-enforce-cpuid' option.
    2. login

    param test: the test object
    param params: the test params
    param env: the test env object
    """

    res = []
    cpu_model_flags_list = params.objects("cpu_model_flags_list")
    for cpu_model_flags in cpu_model_flags_list:
        try:
            error_context.context(
                "Start the guest with %s." % cpu_model_flags, test.log.info
            )
            params["cpu_model_flags"] = cpu_model_flags
            vm = qemu_img_utils.boot_vm_with_images(test, params, env)
            vm.wait_for_login(timeout=360)
        except Exception:
            res.append(
                "Case was failed in smoke test with "
                "parameter(s): %s \n " % cpu_model_flags
            )
            pass
        finally:
            if vm:
                vm.destroy()

    if len(res) > 0:
        error_msg = ""
        for case in res:
            error_msg += case
        test.fail(
            "The failed message(s): \n"
            + error_msg
            + "The number of failed cases is: %s. " % len(res)
        )
