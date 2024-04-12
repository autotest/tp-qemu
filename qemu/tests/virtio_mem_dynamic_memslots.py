from avocado.utils.wait import wait_for

from virttest import error_context

from virttest.utils_misc import normalize_data_size
from provider import virtio_mem_utils


def count_memslots(vm):
    """
    Returns the number of memslots assigned to the current virtio-mem device
    :param vm: the VM object
    """
    output = vm.monitor.info("mtree").splitlines()
    memslots = set()
    for memory_region in output:
        memory_region = memory_region.strip()
        if "mem-vmem0" in memory_region and "memslot" in memory_region:
            memslots.add(memory_region)
    return len(memslots)


def validate_memslots(expected_memslots, test, vm):
    """
    Validates the total number of memslots is the expected one
    :param expected_memslots: the expected number of memslots
    :param test: QEMU test object
    :param vm: the VM object
    """
    if not wait_for(lambda: count_memslots(vm) == expected_memslots, 10):
        test.fail("The number of memslots is not %d" % expected_memslots)


@error_context.context_aware
def run(test, params, env):
    """
    Virtio-mem dynamic memslots on/off test
    1) Boot VM
    2) Check memory-devices
    3) Check memory tree
    4) Resize virtio-mem device
    5) Validate the virtio-mem device now has the correct number of memslots
    6) Sets requested-size to 0 and check again the memslots

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    requested_size_vmem_test = params.get("requested-size_test_vmem0")
    total_memslots = params.get_numeric("total_memslots", 4)
    dynamic_memslots = params.get_boolean("dynamic_memslots", True)

    virtio_mem_model = "virtio-mem-pci"
    if "-mmio:" in params.get("machine_type"):
        virtio_mem_model = "virtio-mem-device"
    vmem_dev = vm.devices.get_by_params({"driver": virtio_mem_model})[0]
    device_id = vmem_dev.get_qid()

    virtio_mem_utils.check_memory_devices(device_id, "0", 0, vm, test)

    validate_memslots(0, test, vm)

    req_size_normalized = int(float(normalize_data_size(requested_size_vmem_test, "B")))
    vm.monitor.qom_set(device_id, "requested-size", req_size_normalized)

    if dynamic_memslots:
        validate_memslots(total_memslots, test, vm)
    else:
        validate_memslots(0, test, vm)

    vm.monitor.qom_set(device_id, "requested-size", 0)
    validate_memslots(0, test, vm)
