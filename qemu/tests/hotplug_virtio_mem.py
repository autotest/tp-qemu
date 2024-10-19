import re
import time

from virttest import error_context, utils_misc, utils_qemu
from virttest.qemu_monitor import QMPCmdError
from virttest.utils_misc import normalize_data_size
from virttest.utils_test.qemu import MemoryHotplugTest
from virttest.utils_version import VersionInterval

from provider import virtio_mem_utils


@error_context.context_aware
def run(test, params, env):
    """
    Virtio-mem hotplug test
    1) Boot guest
    2) Hotplug virtio-mem device
    3) Check virtio-mem device
    4) Resize virtio-mem device twice
    5) Check virtio-mem device
    6) If QEMU allows, try to unplug
    7) Check the expected error message
    8) Resize virtio-mem device to zero
    9) Unplug successfully the virtio-mem device

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    timeout = params.get_numeric("login_timeout", 240)
    threshold = params.get_numeric("threshold", target_type=float)
    qemu_path = utils_misc.get_qemu_binary(params)
    qemu_version = utils_qemu.get_qemu_version(qemu_path)[0]
    error_msg = params.get("error_msg")
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    target_mem = params.get("target_mems")
    hotplug_test = MemoryHotplugTest(test, params, env)
    _, vmem_dev = hotplug_test.hotplug_memory(vm, target_mem)

    device_id = vmem_dev.get_qid()
    requested_size_vmem_test = params.get("requested-size_test_%s" % target_mem)

    node_id = int(vmem_dev.get_param("node"))
    req_size = vmem_dev.get_param("requested-size")
    initial_req_size = str(int(float(normalize_data_size(req_size, "B"))))

    virtio_mem_utils.check_memory_devices(
        device_id, initial_req_size, threshold, vm, test
    )
    virtio_mem_utils.check_numa_plugged_mem(
        node_id, initial_req_size, threshold, vm, test
    )
    for requested_size in requested_size_vmem_test.split():
        req_size_normalized = int(float(normalize_data_size(requested_size, "B")))
        vm.monitor.qom_set(device_id, "requested-size", req_size_normalized)
        time.sleep(30)
        virtio_mem_utils.check_memory_devices(
            device_id, requested_size, threshold, vm, test
        )
        virtio_mem_utils.check_numa_plugged_mem(
            node_id, requested_size, threshold, vm, test
        )
    if qemu_version in VersionInterval("[8.1.0,)"):
        try:
            hotplug_test.unplug_memory(vm, target_mem)
        except QMPCmdError as e:
            if not re.search(error_msg, str(e.data)):
                test.fail("Unexpected error message: %s" % str(e.data))
            test.log.info(error_msg)
        else:
            test.fail(
                "%s shouldn't have been unplugged! 'size' is greater than 0"
                % target_mem
            )

        vm.monitor.qom_set(device_id, "requested-size", 0)
        time.sleep(10)
        hotplug_test.unplug_memory(vm, target_mem)

    session.close()
