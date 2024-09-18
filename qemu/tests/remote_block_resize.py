import json

from avocado.utils import wait
from virttest import data_dir, error_context, qemu_storage, utils_disk, utils_test
from virttest.qemu_capabilities import Flags
from virttest.utils_windows import drive


@error_context.context_aware
def run(test, params, env):
    """
    KVM block resize test:

    1) Start guest with both data disk and system disk.
    2) Extend/shrink data disk in guest.
    3) Verify the data disk size match expected size.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def verify_disk_size(session, os_type, disk):
        """
        Verify the current block size match with the expected size.
        """
        current_size = utils_disk.get_disk_size(session, os_type, disk)
        accept_ratio = float(params.get("accept_ratio", 0))
        if current_size <= block_size and current_size >= block_size * (
            1 - accept_ratio
        ):
            test.log.info(
                "Block Resizing Finished !!! \n"
                "Current size %s is same as the expected %s",
                current_size,
                block_size,
            )
            return True
        else:
            test.log.error("Current: %s\nExpect: %s\n", current_size, block_size)
            return False

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    driver_name = params.get("driver_name")
    os_type = params["os_type"]
    img_size = params.get("image_size_stg", "10G")
    data_image = params.get("images").split()[-1]
    data_image_params = params.object_params(data_image)
    img = qemu_storage.QemuImg(data_image_params, data_dir.get_data_dir(), data_image)
    filters = {}
    data_image_dev = ""
    if vm.check_capability(Flags.BLOCKDEV):
        filters = {"driver": data_image_params.get("image_format", "qcow2")}
    else:
        filters = {"file": img.image_filename}

    # get format node-name(-blockdev) or device name(-drive)
    for dev in vm.devices.get_by_params(filters):
        if dev.aobject == data_image:
            data_image_dev = dev.get_qid()

    if not data_image_dev:
        test.error("Cannot find device to resize.")

    block_virtual_size = json.loads(img.info(force_share=True, output="json"))[
        "virtual-size"
    ]

    session = vm.wait_for_login(timeout=timeout)
    if os_type == "windows" and driver_name:
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name, timeout
        )
    if os_type == "linux":
        disk = sorted(utils_disk.get_linux_disks(session).keys())[0]
    else:
        disk = utils_disk.get_windows_disks_index(session, img_size)[0]

    for ratio in params.objects("disk_change_ratio"):
        block_size = int(int(block_virtual_size) * float(ratio))
        # The new size must be a multiple of 512 for windows
        if os_type == "windows" and block_size % 512 != 0:
            block_size = int(block_size / 512) * 512
        error_context.context(
            "Change disk size to %s in monitor" % block_size, test.log.info
        )

        if vm.check_capability(Flags.BLOCKDEV):
            args = (None, block_size, data_image_dev)
        else:
            args = (data_image_dev, block_size)
        vm.monitor.block_resize(*args)

        # to apply the new size
        if params.get("guest_prepare_cmd", ""):
            session.cmd(params.get("guest_prepare_cmd"))
        if params.get("need_reboot") == "yes":
            session = vm.reboot(session=session)
        if params.get("need_rescan") == "yes":
            drive.rescan_disks(session)

        if not wait.wait_for(
            lambda: verify_disk_size(session, os_type, disk), 20, 0, 1, "Block Resizing"
        ):
            test.fail("The current block size is not the same as expected.\n")

    session.close()
