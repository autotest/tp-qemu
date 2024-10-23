"""IO-Throttling cdrom relevant testing"""

from virttest import error_context
from virttest.qemu_capabilities import Flags

from provider.cdrom import QMPEventCheckCDChange, QMPEventCheckCDEject


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    Test cdrom operation with throttle feature.
    1) Boot up guest with cdrom device in throttle groups.
    2) Query cdrom device.
    3) Execute change media operation
    4) Query cdrom device
    5) Execute eject media operation
    """

    error_context.context("Get the main VM", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    vm.wait_for_login(timeout=120)

    p_dict = {"removable": True, "drv": "throttle"}
    device_name = vm.get_block(p_dict)

    if device_name is None:
        test.fail("Fail to get cdrom device with drv throttle")

    test.log.info("Found cdrom device %s", device_name)

    eject_check = QMPEventCheckCDEject(vm, device_name)
    change_check = QMPEventCheckCDChange(vm, device_name)

    monitor = vm.get_monitors_by_type("qmp")[0]
    if vm.check_capability(Flags.BLOCKDEV):
        qdev = vm.devices.get_qdev_by_drive(device_name)
        monitor.blockdev_open_tray(qdev, force=True)

    # change media
    new_img_name = params.get("new_img_name")
    error_context.context("Insert new image to device.", test.log.info)
    with change_check:
        vm.change_media(device_name, new_img_name)

    # After change medium throttle property is expected to be removed
    error_context.context("Query cdrom device with new image.", test.log.info)
    p_dict = {"removable": True, "file": new_img_name}
    device_name = vm.get_block(p_dict)

    if device_name is None:
        test.fail("Fail to get cdrom device with new image after change")

    # eject media
    error_context.context("Eject device.", test.log.info)
    with eject_check:
        monitor.blockdev_open_tray(qdev, force=True)
        monitor.blockdev_remove_medium(qdev)
