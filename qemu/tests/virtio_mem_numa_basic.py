import time

from virttest import error_context

from virttest.utils_misc import normalize_data_size
from provider import virtio_mem_utils


@error_context.context_aware
def run(test, params, env):
    """
    Memory share and discard-data hotplug test
    1) Boot guest with two virtio-mem devices
    2) Check virtio-mem devices
    3) Resize virtio-mem devices
    4) Check virtio-mem devices
    5) Resize virtio-mem devices to the maximum
    6) Check virtio-mem devices
    7) Resize virtio-mem devices to the minimum
    8) Check virtio-mem devices

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    timeout = int(params.get("login_timeout", 240))
    threshold = params.get_numeric("threshold", target_type=float)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)
    virtio_mem_model = 'virtio-mem-pci'
    if '-mmio:' in params.get("machine_type"):
        virtio_mem_model = 'virtio-mem-device'
    for i, vmem_dev in enumerate(vm.devices.get_by_params({'driver': virtio_mem_model})):
        device_id = vmem_dev.get_qid()
        requested_size_vmem = params.get("requested-size_test_vmem%d" % i)
        node_id = int(vmem_dev.params.get("node"))
        for requested_size in requested_size_vmem.split():
            req_size_normalized = int(float(normalize_data_size(requested_size, 'B')))
            vm.monitor.qom_set(device_id, "requested-size", req_size_normalized)
            time.sleep(30)
            virtio_mem_utils.check_memory_devices(device_id, requested_size, threshold, vm, test)
            virtio_mem_utils.check_numa_plugged_mem(node_id, requested_size, threshold, vm, test)

    session.close()
    error_context.context("Shutdown guest...", test.log.debug)
    vm.destroy()
