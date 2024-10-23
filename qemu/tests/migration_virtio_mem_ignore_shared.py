import ast
import time

from virttest import error_context, utils_test
from virttest.utils_misc import normalize_data_size

from provider import virtio_mem_utils


@error_context.context_aware
def run(test, params, env):
    """
    Migrates a guest with virtio-mem device and x-ignore-shared enabled
    1) Boot source and destination VMs with a virtio-mem device
       and shared memory.
    2) Enable x-ignore-shared capability in both hosts.
    3) Check the capability is enabled.
    4) Start stress tool in source VM.
    5) Migrate VM.
    6) Memory tool stress is stopped and migration completed.
    7) Prove the total ram migrated is a little amount.
    8) Resize the virtio-mem device in destination a couple of times.
    9) Ascertain the virtio-mem device work properly.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    threshold = params.get_numeric("threshold", target_type=float)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    # Stress in source VM
    error_context.base_context("Install and compile stress tool", test.log.info)
    test_mem = params.get_numeric("mem", target_type=float)
    params["stress_args"] = "--cpu 4 --io 4 --vm 2 --vm-bytes %fM" % float(
        test_mem * 0.8
    )
    clone = None
    try:
        stress_test = utils_test.VMStress(vm, "stress", params)
        error_context.context("Stress test start", test.log.info)
        try:
            stress_test.load_stress_tool()
            # Migration
            error_context.base_context(
                "Set migrate capabilities and do migration", test.log.info
            )
            capabilities = ast.literal_eval(
                params.get("migrate_capabilities", "{'x-ignore-shared': 'on'}")
            )
            mig_timeout = params.get_numeric("mig_timeout", 1200, float)
            mig_protocol = params.get("migration_protocol", "tcp")
            clone = vm.migrate(
                mig_timeout,
                mig_protocol,
                env=env,
                migrate_capabilities=capabilities,
                not_wait_for_migration=True,
            )

            vm.wait_for_migration(mig_timeout)

            clone.resume()
            error_context.context("Check the total ram migrated", test.log.info)
            total_mem_migrated = str(vm.monitor.info("migrate")["ram"]["total"])
            total_mem_migrated = float(normalize_data_size(total_mem_migrated, "M"))
            test.log.debug("Total memory migrated: %f", total_mem_migrated)

            mem_threshold = params.get_numeric("mem_threshold", target_type=float)
            if total_mem_migrated > test_mem * mem_threshold:
                test.error("Error, more memory than expected has been migrated!")

            test.log.debug("Stress tool running status: %s", stress_test.app_running())
            if not stress_test.app_running():
                test.fail("Stress tool must be running at this point!")

        except utils_test.StressError as guest_info:
            test.error(guest_info)

        finally:
            stress_test.unload_stress()
            stress_test.clean()

        error_context.base_context(
            "Test virtio-mem device on destination VM", test.log.info
        )
        virtio_mem_model = "virtio-mem-pci"
        if "-mmio:" in params.get("machine_type"):
            virtio_mem_model = "virtio-mem-device"
        vmem_dev = clone.devices.get_by_params({"driver": virtio_mem_model})[0]
        device_id = vmem_dev.get_qid()
        requested_size_vmem = params.get("requested-size_test_vmem0")
        for requested_size in requested_size_vmem.split():
            req_size_normalized = int(float(normalize_data_size(requested_size, "B")))
            clone.monitor.qom_set(device_id, "requested-size", req_size_normalized)
            time.sleep(45)
            virtio_mem_utils.check_memory_devices(
                device_id, requested_size, threshold, clone, test
            )
            virtio_mem_utils.check_numa_plugged_mem(
                0, requested_size, threshold, clone, test
            )
    finally:
        if clone:
            clone.destroy(gracefully=False)
            env.unregister_vm("%s_clone" % vm.name)
