import re

from avocado.utils.wait import wait_for
from virttest import data_dir, error_context, utils_disk, utils_misc, utils_test
from virttest.qemu_storage import QemuImg, get_image_json

from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Test the block write threshold for block devices.
    Steps:
        1. Create a data disk.
        2. Boot up the guest with a data disk attached.
        3. Set block write threshold for the data block drive in QMP.
        4. Login to guest then do stress io to trigger the threshold.
        5. Verify the event 'BLOCK_WRITE_THRESHOLD' in QMP.
        6. Set block write threshold to 0 for the data block drive in QMP
           which will not trigger the threshold.
        7. Login to guest then do stress io.
        8. Verify event 'BLOCK_WRITE_THRESHOLD' in QMP which should not be
           triggered.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def get_node_name(image_tag):
        """Get the node name."""
        img_params = params.object_params(image_tag)
        root_dir = data_dir.get_data_dir()
        img = QemuImg(img_params, root_dir, image_tag)
        filename = img.image_filename
        if img.image_format == "luks":
            filename = get_image_json(image_tag, img_params, root_dir)
        return vm.get_block({"filename": filename})

    def set_block_write_threshold(monitor, node_name, size):
        """Set block write threshold for the block drive."""
        error_context.context(
            "Set block write threshold to %s for the block " "drive in QMP." % size,
            test.log.info,
        )
        monitor.cmd(
            "block-set-write-threshold",
            {"node-name": node_name, "write-threshold": size},
        )

    def verify_block_write_threshold_event(monitor):
        """Verify the event 'BLOCK_WRITE_THRESHOLD' in QMP."""
        return wait_for(lambda: monitor.get_event("BLOCK_WRITE_THRESHOLD"), 30)

    def get_data_disk(session):
        """Get the data disk."""
        if is_linux:
            extra_params = params["blk_extra_params_%s" % data_img_tag]
            drive_id = re.search(r"(serial|wwn)=(\w+)", extra_params, re.M).group(2)
            return utils_misc.get_linux_drive_path(session, drive_id)
        return sorted(session.cmd("wmic diskdrive get index").split()[1:])[-1]

    def _io_stress_linux(target):
        session.cmd(params["dd_cmd"] % target, 180)

    def _io_stress_windows(target):
        fio = generate_instance(params, vm, "fio")
        try:
            fio.run(params["fio_opts"] % target)
        finally:
            fio.clean()

    def run_io_stress(stress_func, target):
        """Run io stress inside guest."""
        error_context.context("Run io stress inside guest.", test.log.info)
        stress_func(target)

    is_linux = params["os_type"] == "linux"
    data_img_tag = params["images"].split()[-1]
    data_img_size = params["image_size_%s" % data_img_tag]
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=360)
    target = get_data_disk(session)
    if not is_linux:
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, params["driver_name"]
        )
        utils_disk.update_windows_disk_attributes(session, target)
        target = utils_disk.configure_empty_windows_disk(
            session, target, data_img_size
        )[-1]

    qmp_monitor = vm.monitors[0]
    node_name = get_node_name(data_img_tag)
    set_block_write_threshold(qmp_monitor, node_name, int(params["threshold_size"]))
    stress_func = locals()["_io_stress_%s" % ("linux" if is_linux else "windows")]
    run_io_stress(stress_func, target)
    if not verify_block_write_threshold_event(qmp_monitor):
        test.fail("Failed to get the event 'BLOCK_WRITE_THRESHOLD'.")

    qmp_monitor.clear_event("BLOCK_WRITE_THRESHOLD")
    set_block_write_threshold(qmp_monitor, node_name, 0)
    run_io_stress(stress_func, target)
    if verify_block_write_threshold_event(qmp_monitor):
        test.fail("Failed to disable threshold.")
