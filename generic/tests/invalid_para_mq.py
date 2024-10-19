import re

from virttest import env_process, error_context, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Enable MULTI_QUEUE feature in guest

    1) Boot up VM with wrong queues number
    2) Check qemu not coredump
    3) Check the qemu can report the error

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    vm_name = params["main_vm"]
    params["start_vm"] = "yes"
    nic_queues = int(params["queues"])
    try:
        error_context.context(
            "Boot the vm using queues %s'" % nic_queues, test.log.info
        )
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        vm.destroy()
        test.error("Qemu start up normally, didn't quit as expect")
    except utils_net.NetError as exp:
        message = str(exp)
        # clean up tap device when qemu coredump to ensure,
        # to ensure next test has clean network envrioment
        if (
            hasattr(exp, "ifname")
            and exp.ifname
            and exp.ifname in utils_net.get_host_iface()
        ):
            try:
                bridge = params.get("netdst", "switch")
                utils_net.del_from_bridge(exp.ifname, bridge)
            except Exception as warning:
                test.log.warning(
                    "Error occurent when clean tap device(%s)", str(warning)
                )
        error_context.context("Check Qemu not coredump", test.log.info)
        if "(core dumped)" in message:
            test.fail("Qemu core dumped when boot with invalid parameters.")
        error_context.context("Check Qemu quit with except message", test.log.info)
        if not re.search(params["key_words"], message, re.M | re.I):
            test.log.info("Error message: %s", message)
            test.fail("Can't detect expect error")
