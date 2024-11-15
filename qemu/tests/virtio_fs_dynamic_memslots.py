import os

from avocado.utils import process
from virttest import error_context, utils_disk, utils_misc, utils_test

from provider import virtio_fs_utils, virtio_mem_utils, win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    1) Boot a guest VM with virtio-fs device
    2) Check virtiofs basic functionality works
    3) Validate the virtio-mem device has the correct number of memslots
    4) Check memory size in the guest
    4) Execute basic IO test in the guest
    5) Clean environment

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    os_type = params["os_type"]
    cmd_md5 = params.get("cmd_md5")
    test_file = params.get("test_file")
    io_timeout = params.get_numeric("io_timeout")
    fs_source = params.get("fs_source_dir")
    fs_target = params.get("fs_target")
    fs_dest = params.get("fs_dest")
    mem_object_id = params.get("mem_devs")
    total_memslots = params.get_numeric("total_memslots")
    requested_size_mem = params.get("requested-size_memory_vmem0")
    hmp_timeout = params.get_numeric("hmp_timeout", 10)

    virtio_mem_model = "virtio-mem-pci"
    if "-mmio:" in params.get("machine_type"):
        virtio_mem_model = "virtio-mem-device"
    vmem_dev = vm.devices.get_by_params({"driver": virtio_mem_model})[0]
    device_id = vmem_dev.get_qid()

    try:
        if os_type == "windows":
            driver_name = params["driver_name"]
            # Check whether windows driver is running,and enable driver verifier
            session = utils_test.qemu.windrv_check_running_verifier(
                session, vm, test, driver_name
            )
            # create virtiofs service
            viofs_svc_name = params["viofs_svc_name"]
            virtio_fs_utils.create_viofs_service(
                test, params, session, service=viofs_svc_name
            )
            # start virtiofs service
            error_context.context(
                "Start virtiofs service in the windows guest.", test.log.info
            )
            debug_log_operation = params.get("debug_log_operation")
            if debug_log_operation:
                session = virtio_fs_utils.operate_debug_log(
                    test, params, session, vm, debug_log_operation
                )
            virtio_fs_utils.start_viofs_service(test, params, session)

        if os_type == "linux":
            utils_misc.make_dirs(fs_dest, session)
            error_context.context(
                "Mount virtiofs target %s to %s inside"
                " guest." % (fs_target, fs_dest),
                test.log.info,
            )
            if not utils_disk.mount(fs_target, fs_dest, "virtiofs", session=session):
                utils_misc.safe_rmdir(fs_dest, session=session)
                test.fail("Failed to mount virtiofs {fs_target}.")

        # Check md5sum for file on guest and host
        host_file = os.path.join(fs_source, test_file)

        if os_type == "linux":
            guest_file = os.path.join(fs_dest, test_file)
            cmd_md5_vm = cmd_md5 % guest_file
        else:
            volume_letter = virtio_fs_utils.get_virtiofs_driver_letter(
                test, fs_target, session
            )
            guest_file = f"\\{test_file}"
            cmd_md5_vm = cmd_md5 % (volume_letter, guest_file)

        md5_guest = session.cmd_output(cmd_md5_vm, io_timeout).strip().split()[0]
        md5_host = (
            process.run("md5sum %s" % host_file, io_timeout)
            .stdout_text.strip()
            .split()[0]
        )
        if md5_guest != md5_host:
            test.fail("The md5 value of host is not same to guest.")

        # Check memslots
        virtio_mem_utils.validate_memslots(
            total_memslots, test, vm, mem_object_id, hmp_timeout
        )

        virtio_mem_utils.check_memory_devices(
            device_id, requested_size_mem, 0, vm, test
        )
        virtio_fs_utils.basic_io_test(test, params, session)
    finally:
        if os_type == "linux":
            utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
            utils_misc.safe_rmdir(fs_dest, session=session)
        if os_type == "windows":
            session = vm.wait_for_login()
            virtio_fs_utils.stop_viofs_service(test, params, session)
            virtio_fs_utils.delete_viofs_serivce(test, params, session)
            win_driver_utils.memory_leak_check(vm, test, params)
        session.close()
