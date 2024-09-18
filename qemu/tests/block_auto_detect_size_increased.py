import re

from virttest import data_dir, storage, utils_disk, utils_test
from virttest.qemu_capabilities import Flags
from virttest.qemu_storage import get_image_json
from virttest.utils_numeric import normalize_data_size


def run(test, params, env):
    """
    Test to check the size of data disk increased can be detected
    automatically inside windows guest.

    Steps:
        1) Start a windows guest with a data disk and format it.
        2) Increase this data disk by qmp command.
        3) Copy a file to this data disk.
        4) The guest can detect the data disk size increased
           automatically.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def increase_block_device(dev):
        """Increase the block device."""
        test.log.info("Start to increase image '%s' to %s.", img, img_resize_size)
        resize_size = int(
            float(
                normalize_data_size(
                    re.search(r"(\d+\.?(\d+)?\w)", img_resize_size).group(1), "B"
                )
            )
        )
        args = (dev, resize_size)
        if vm.check_capability(Flags.BLOCKDEV):
            args = (None, resize_size, dev)
        vm.monitor.block_resize(*args)
        return resize_size

    def get_disk_size_by_diskpart(index):
        """Get the disk size by the diskpart."""
        cmd = " && ".join(
            (
                "echo list disk > {0}",
                "echo exit >> {0}",
                "diskpart /s {0}",
                "del /f {0}",
            )
        ).format("disk_script")
        pattern = r"Disk\s+%s\s+Online\s+(\d+\s+\w+)\s+\d+\s+\w+" % index
        return re.search(pattern, session.cmd_output(cmd), re.M).group(1)

    def check_disk_size(index):
        """Check the disk size after increasing inside guest."""
        test.log.info(
            "Check whether the size of disk %s is equal to %s after "
            "increasing inside guest.",
            index,
            img_resize_size,
        )
        v, u = re.search(r"(\d+\.?\d*)\s*(\w?)", img_resize_size).groups()
        size = get_disk_size_by_diskpart(index)
        test.log.info("The size of disk %s is %s", index, size)
        if normalize_data_size(size, u) != v:
            test.fail(
                "The size of disk %s is not equal to %s" % (index, img_resize_size)
            )

    img = params.get("images").split()[-1]
    img_params = params.object_params(img)
    img_size = img_params.get("image_size")
    img_resize_size = img_params.get("image_resize_size")
    root_dir = data_dir.get_data_dir()
    img_filename = storage.get_image_filename(img_params, root_dir)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = utils_test.qemu.windrv_check_running_verifier(
        vm.wait_for_login(), vm, test, "viostor", 300
    )
    indices = utils_disk.get_windows_disks_index(session, img_size)
    utils_disk.update_windows_disk_attributes(session, indices)
    index = indices[0]
    mpoint = utils_disk.configure_empty_windows_disk(session, index, img_size)[0]

    if img_params.get("image_format") == "luks":
        img_filename = get_image_json(img, img_params, root_dir)
    increase_block_device(vm.get_block({"filename": img_filename}))
    vm.copy_files_to("/home/dd_file", "%s:\\dd_file" % mpoint)
    check_disk_size(index)
