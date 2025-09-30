import re

from virttest import utils_net


def run(test, params, env):
    """
    Test net adapter after set NetAdapterrss, this case will:

    1) Boot up VM with specific smp and queues
    2) Configure RSS in VM
    3) Check ndis Poll Mode state
    4) Check traceview output

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    # Enable RSS and setup RSS Queues value
    rss_queues = params["rss_queues"]
    rss, rss_value = params["enable_rss"].split(" ")
    rss_queues, rss_queues_value = (params["setup_rss_queues"] % rss_queues).split(" ")
    utils_net.set_netkvm_param_value(vm, rss, rss_value)
    utils_net.set_netkvm_param_value(vm, rss_queues, rss_queues_value)

    # Check ndis poll mode state
    output = utils_net.get_netkvm_param_value(vm, "*NdisPoll")
    test.log.info("ndis poll mode is %s", output)

    # Check the traceview content
    keyword = params["keyword"]
    result = utils_net.dump_traceview_log_windows(params, vm)
    test.log.info("Traceview log result: %s", result)
    mapping_output = re.findall(keyword, result)
    if not mapping_output:
        test.error("Can't get %s from traceview", keyword)
    return mapping_output
