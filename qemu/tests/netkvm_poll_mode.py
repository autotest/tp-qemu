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
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    # Enable RSS and setup RSS Queues value
    rss_queues_count = params["rss_queues"]
    rss, rss_value = params["enable_rss"].split(" ")
    rss_queues_param, rss_queues_value = (
        params["setup_rss_queues"] % rss_queues_count
    ).split(" ")
    utils_net.set_netkvm_param_value(vm, rss, rss_value)
    utils_net.set_netkvm_param_value(vm, rss_queues_param, rss_queues_value)

    # Check ndis poll mode state
    poll_mode_param = params["poll_mode_name"]
    output = utils_net.get_netkvm_param_value(vm, poll_mode_param)
    test.log.info("ndis poll mode is %s", output)

    # Check the traceview content
    keyword = params["keyword"]
    result = utils_net.dump_traceview_log_windows(params, vm)
    test.log.info("Traceview log result: %s", result)
    mapping_output = re.findall(keyword, result)
    if not mapping_output:
        test.error("Can't get %s from traceview", keyword)
    test.log.info("Found keyword matches: %s", mapping_output)
