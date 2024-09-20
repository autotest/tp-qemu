import time

from virttest import data_dir, error_context
from virttest.qemu_capabilities import Flags
from virttest.qemu_storage import QemuImg, get_image_json

from provider.cdrom import QMPEventCheckCDChange, QMPEventCheckCDEject


@error_context.context_aware
def run(test, params, env):
    """
    change a removable media:
    1) Boot VM with QMP/human monitor enabled.
    2) Connect to QMP/human monitor server.
    3) Eject original cdrom.
    4) Eject original cdrom for second time.
    5) Insert new image to cdrom.
    6) Eject device after add new image by change command.
    7) Insert original cdrom to cdrom.
    8) Try to eject non-removable device w/o force option.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    test.log.info("Wait until device is ready")
    time.sleep(10)

    def check_block(block):
        return True if block in str(vm.monitor.info("block")) else False

    def eject_non_cdrom(device_name, force=False):
        if vm.check_capability(Flags.BLOCKDEV):
            for info_dict in vm.monitor.info("block"):
                if device_name in str(info_dict):
                    qdev = info_dict["qdev"]
                    break
            vm.monitor.blockdev_open_tray(qdev, force)
            return vm.monitor.blockdev_remove_medium(qdev)
        else:
            vm.eject_cdrom(device_name, force)

    orig_img_name = params.get("cdrom_cd1")
    p_dict = {"file": orig_img_name}
    device_name = vm.get_block(p_dict)
    if device_name is None:
        msg = "Fail to get device using image %s" % orig_img_name
        test.fail(msg)

    eject_check = QMPEventCheckCDEject(vm, device_name)
    change_check = QMPEventCheckCDChange(vm, device_name)

    # eject first time
    error_context.context("Eject original device.", test.log.info)
    with eject_check:
        vm.eject_cdrom(device_name, force=True)
    if check_block(orig_img_name):
        test.fail("Fail to eject cdrom %s. " % orig_img_name)

    # eject second time
    error_context.context("Eject original device for second time", test.log.info)
    with eject_check:
        vm.eject_cdrom(device_name)

    # change media
    new_img_name = params.get("new_img_name")
    error_context.context("Insert new image to device.", test.log.info)
    with change_check:
        vm.change_media(device_name, new_img_name)
    if not check_block(new_img_name):
        test.fail("Fail to change cdrom to %s." % new_img_name)

    # eject after change
    error_context.context(
        "Eject device after add new image by change command", test.log.info
    )
    with eject_check:
        vm.eject_cdrom(device_name, True)
    if check_block(new_img_name):
        test.fail("Fail to eject cdrom %s." % orig_img_name)

    # change back to orig_img_name
    error_context.context(
        "Insert %s to device %s" % (orig_img_name, device_name), test.log.info
    )
    with change_check:
        vm.change_media(device_name, orig_img_name)
    if not check_block(orig_img_name):
        test.fail("Fail to change cdrom to %s." % orig_img_name)

    error_context.context(
        "Eject device after add org image by change command", test.log.info
    )
    with eject_check:
        vm.eject_cdrom(device_name, True)
    # change again
    error_context.context(
        "Insert %s to device %s" % (new_img_name, device_name), test.log.info
    )
    with change_check:
        vm.change_media(device_name, new_img_name)
    if not check_block(new_img_name):
        test.fail("Fail to change cdrom to %s." % new_img_name)

    # eject non-removable
    error_context.context("Try to eject non-removable device", test.log.info)
    p_dict = {"removable": False}
    device_name = vm.get_block(p_dict)
    if vm.check_capability(Flags.BLOCKDEV):
        img_tag = params["images"].split()[0]
        root_dir = data_dir.get_data_dir()
        sys_image = QemuImg(params, root_dir, img_tag)
        filename = sys_image.image_filename
        if sys_image.image_format == "luks":
            filename = get_image_json(img_tag, params, root_dir)
        device_name = vm.get_block({"filename": filename})
    if device_name is None:
        test.error("Could not find non-removable device")
    try:
        if params.get("force_eject", "no") == "yes":
            eject_non_cdrom(device_name, force=True)
        else:
            eject_non_cdrom(device_name)
    except Exception as e:
        if "is not removable" not in str(e):
            test.fail(e)
        test.log.debug("Catch exception message: %s", e)
    if not check_block(device_name):
        test.fail("Could remove non-removable device!")

    session.close()
