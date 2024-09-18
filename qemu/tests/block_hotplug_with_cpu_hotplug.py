from virttest import error_context, utils_disk, utils_misc
from virttest.utils_misc import get_linux_drive_path
from virttest.utils_windows.drive import get_disk_props_by_serial_number

from provider import cpu_utils, win_wora
from provider.block_devices_plug import BlockDevicesPlug


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of block devices after
    hotplug a cpu device.

    1) Boot up guest
    2) Hotplug device and verify in qtree
    3) Check hotplug devices in guest
    4) Hotpulg a cpu device
    5) Hotplug device again and verify in qtree.
    6) Check hotplug devices in guest

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def _get_window_disk_index_by_serial(serial):
        idx_info = get_disk_props_by_serial_number(session, serial, ["Index"])
        if idx_info:
            return idx_info["Index"]
        test.fail("Not find expected disk %s" % serial)

    def _check_disk_in_guest(img):
        os_type = params["os_type"]
        test.log.debug("Check disk %s in guest", img)
        if os_type == "windows":
            img_size = params.get("image_size_%s" % img)
            cmd = utils_misc.set_winutils_letter(session, guest_cmd)
            disk = _get_window_disk_index_by_serial(img)
            utils_disk.update_windows_disk_attributes(session, disk)
            test.log.info("Clean disk:%s", disk)
            utils_disk.clean_partition_windows(session, disk)
            test.log.info("Formatting disk:%s", disk)
            driver = utils_disk.configure_empty_disk(session, disk, img_size, os_type)[
                0
            ]
            output_path = driver + ":\\test.dat"
            cmd = cmd.format(output_path)
        else:
            output_path = get_linux_drive_path(session, img)
            cmd = guest_cmd.format(output_path)

        session.cmd(cmd)

    vcpu_devices = params.objects("vcpu_devices")
    img_name_list = params.get("images").split()
    guest_cmd = params.get("guest_cmd")

    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    if params.get_boolean("workaround_need"):
        win_wora.modify_driver(params, session)

    error_context.context("Plug device", test.log.info)
    plug = BlockDevicesPlug(vm)
    plug.hotplug_devs_serial(img_name_list[1])
    _check_disk_in_guest(img_name_list[1])

    for vcpu_dev in vcpu_devices:
        error_context.context("Hotplug vcpu device: %s" % vcpu_dev, test.log.info)
        vm.hotplug_vcpu_device(vcpu_dev)
    if not utils_misc.wait_for(lambda: cpu_utils.check_if_vm_vcpus_match_qemu(vm), 60):
        test.fail("Actual number of guest CPUs is not equal to expected")

    # FIXME: win2016 guest will reboot once hotplug a cpu
    # so we need to reacquire the session.
    if params.get_boolean("workaround_need"):
        session = vm.wait_for_login()

    error_context.context("Plug another device", test.log.info)
    plug.hotplug_devs_serial(img_name_list[2])
    _check_disk_in_guest(img_name_list[2])

    session.close()
