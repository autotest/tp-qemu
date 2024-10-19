import time

from virttest import error_context
from virttest.utils_misc import normalize_data_size

from provider import virtio_mem_utils


@error_context.context_aware
def run(test, params, env):
    """
    Virtio-mem dynamic memslots with migration test
    1) Boot VM
    2) Resize virtio-mem device
    3) Do migration
    4) Check virtio-mem size in dst host
    5) Validate the virtio-mem device now has the correct number of memslots

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    requested_size_vmem_test = params.get("requested-size_test_vmem0")
    total_memslots = params.get_numeric("total_memslots", 4)
    mem_object_id = params["mem_devs"]
    timeout = params.get_numeric("timeout", 10)

    device_id = "virtio_mem-%s" % mem_object_id

    req_size_normalized = int(float(normalize_data_size(requested_size_vmem_test, "B")))
    vm.monitor.qom_set(device_id, "requested-size", req_size_normalized)

    time.sleep(10)
    virtio_mem_utils.check_memory_devices(
        device_id, requested_size_vmem_test, 0, vm, test
    )

    mig_timeout = params.get_numeric("mig_timeout", 1200, float)
    mig_protocol = params.get("migration_protocol", "tcp")
    vm.migrate(mig_timeout, mig_protocol, env=env)

    virtio_mem_utils.check_memory_devices(
        device_id, requested_size_vmem_test, 0, vm, test
    )

    virtio_mem_utils.validate_memslots(total_memslots, test, vm, mem_object_id, timeout)
