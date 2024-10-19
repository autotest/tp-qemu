import re
import time

from virttest import error_context
from virttest.qemu_monitor import QMPCmdError
from virttest.utils_misc import normalize_data_size

from provider import virtio_mem_utils


@error_context.context_aware
def run(test, params, env):
    """
    Do migration of a virtio-mem device consuming hugepages
    1) Setup hugepages in source and destination hosts
    2) Boot VMs in source and destination hosts
    3) Do migration
    4) Check virtio-mem device
    5) Resize virtio-mem devices to a different value
    6) Check virtio-mem device

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    error_msg = params.get(
        "error_msg", "Error: 'requested-size' cannot exceed the memory backend size"
    )

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login()
    threshold = params.get_numeric("threshold", target_type=float)
    mem_object_id = params["mem_devs"].split().pop()
    initial_req_size = params.get("requested-size_memory_%s" % mem_object_id)
    requested_size_vmem = params.get("requested-size_test_%s" % mem_object_id)
    requested_size_vmem_fail = params.get("requested-size_fail_%s" % mem_object_id)
    device_id = "virtio_mem-%s" % mem_object_id
    node_id = params.get_numeric("node_memory_%s" % mem_object_id)

    mig_timeout = params.get_numeric("mig_timeout", 1200, float)
    mig_protocol = params.get("migration_protocol", "tcp")
    vm.migrate(mig_timeout, mig_protocol, env=env)

    virtio_mem_utils.check_memory_devices(
        device_id, initial_req_size, threshold, vm, test
    )
    virtio_mem_utils.check_numa_plugged_mem(
        node_id, initial_req_size, threshold, vm, test
    )

    try:
        error_context.base_context(
            "Setting 'requested-size' to a higher value", test.log.info
        )
        req_size_normalized = int(
            float(normalize_data_size(requested_size_vmem_fail, "B"))
        )
        vm.monitor.qom_set(device_id, "requested-size", req_size_normalized)
    except QMPCmdError as e:
        if not re.search(error_msg, str(e.data)):
            test.fail("Cannot get expected error message: %s" % error_msg)

    req_size_normalized = int(float(normalize_data_size(requested_size_vmem, "B")))
    vm.monitor.qom_set(device_id, "requested-size", req_size_normalized)
    time.sleep(10)
    virtio_mem_utils.check_memory_devices(
        device_id, requested_size_vmem, threshold, vm, test
    )
    virtio_mem_utils.check_numa_plugged_mem(
        node_id, requested_size_vmem, threshold, vm, test
    )
