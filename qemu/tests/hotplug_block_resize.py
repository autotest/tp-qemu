import json
import re

from virttest import (
    data_dir,
    error_context,
    qemu_storage,
    storage,
    utils_disk,
    utils_misc,
    utils_test,
)
from virttest.qemu_capabilities import Flags
from virttest.utils_numeric import normalize_data_size

from provider.block_devices_plug import BlockDevicesPlug
from provider.storage_benchmark import generate_instance

ENLARGE, SHRINK = ("enlarge", "shrink")


@error_context.context_aware
def run(test, params, env):
    """
    Test to hot plug with block resize.
    Steps:
        1) Boot the guest with system disk.
        2) Hotplug a virtio disk via qmp.
        3) For Windows: check whether viostor.sys verifier enabled in
           guest.
        4) block_resize data disk, e.g, enlarge to 10GB; shrink to 1GB.
        5) Check the disk using qemu-img check on host and do io test
           in guest.
        6) Reboot or shutdown guest by qmp and shell.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def _change_vm_power():
        """Change the vm power."""
        method, command = params["command_opts"].split(",")
        test.log.info("Sending command(%s): %s", method, command)
        if method == "shell":
            power_session = vm.wait_for_login(timeout=360)
            power_session.sendline(command)
        else:
            getattr(vm.monitor, command)()
        if shutdown_vm:
            if not utils_misc.wait_for(lambda: vm.monitor.get_event("SHUTDOWN"), 600):
                raise test.fail("Not received SHUTDOWN QMP event.")

    def _check_vm_status(timeout=600):
        """Check the status of vm."""
        action = "shutdown" if shutdown_vm else "login"
        if not getattr(vm, "wait_for_%s" % action)(timeout=timeout):
            test.fail("Failed to %s vm." % action)

    def _block_resize(dev):
        """Resize the block size."""
        resize_size = int(
            float(
                normalize_data_size(
                    re.search(r"(\d+\.?(\d+)?\w)", params["resize_size"]).group(1), "B"
                )
            )
        )
        size = (
            str(data_image_size + resize_size)
            if resize_op == ENLARGE
            else str(data_image_size - resize_size)
        )
        test.log.info("Start to %s %s to %sB.", resize_op, plug[0], size)
        args = (None, size, dev) if vm.check_capability(Flags.BLOCKDEV) else (dev, size)
        vm.monitor.block_resize(*args)
        return size

    def _check_img_size(size):
        """Check the size of image after resize."""
        img = qemu_storage.QemuImg(
            data_image_params, data_dir.get_data_dir(), data_image
        )
        if json.loads(img.info(True, "json"))["virtual-size"] != int(size):
            test.fail(
                "The virtual size is not equal to %sB after %s." % (size, resize_op)
            )

    shutdown_vm = params.get("shutdown_vm", "no") == "yes"
    reboot = params.get("reboot_vm", "no") == "yes"
    data_image = params.get("images").split()[-1]
    data_image_params = params.object_params(data_image)
    data_image_size = int(
        float(normalize_data_size(data_image_params.get("image_size"), "B"))
    )
    data_image_filename = storage.get_image_filename(
        data_image_params, data_dir.get_data_dir()
    )
    resize_op = SHRINK if "-" in params["resize_size"] else ENLARGE
    os_type = params["os_type"]
    is_windows = os_type == "windows"

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=360)

    if is_windows:
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, params["driver_name"], 300
        )
    plug = BlockDevicesPlug(vm)
    plug.hotplug_devs_serial()
    block_size = _block_resize(vm.get_block({"file": data_image_filename}))
    _check_img_size(block_size)

    iozone = generate_instance(params, vm, "iozone")
    try:
        if is_windows:
            if not utils_disk.update_windows_disk_attributes(session, plug[:]):
                test.fail("Failed to clear readonly and online on %s." % plug[:])
        mount_point = utils_disk.configure_empty_disk(
            session, plug[0], block_size + "B", os_type
        )[0]
        iozone_size = str(int(float(normalize_data_size(block_size)))) + "M"
        iozone.run(
            params["iozone_options"].format(mount_point, iozone_size),
            float(params["iozone_timeout"]),
        )
    finally:
        iozone.clean()
        if shutdown_vm or reboot:
            _change_vm_power()
            _check_vm_status()
