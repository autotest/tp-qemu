"""VDPA blk vhost vdpa test"""

from aexpect import ShellCmdError
from avocado.core import exceptions
from avocado.utils import process
from virttest import env_process, utils_disk, utils_misc, virt_vm
from virttest.utils_misc import get_linux_drive_path
from virttest.utils_windows.drive import get_disk_props_by_serial_number

from provider.block_devices_plug import BlockDevicesPlug
from provider.vdpa_sim_utils import VhostVdpaBlkSimulatorTest


def run(test, params, env):
    """
    VDPA blk vhost vdpa test. It tests multiple scenarios:
    multi-disks,hotplug-unplug,and blockdev options
    Multi-disks steps:
        1) Setup VDPA simulator ENV and create vhost-vdpa devices.
        2) Boot VM with multi vdpa-blk disks
        3) Verify disk in guest
        4) Destroy VM
        5) Destroy vhost-vdpa devices on host
        6) Destroy VDPA simulator ENV
    Hotplug-unplug test steps:
        1) Setup VDPA simulator ENV and create vhost-vdpa devices.
        2) Boot VM
        3) Hotplug the vhost-vdpa disks
        4) Verify disks in guest
        5) Unplug those vdpa-blk disks
        6) Destroy VM
        7) Destroy vhost-vdpa devices on host
        8) Destroy VDPA simulator ENV
    Blockdev other options test
        The test steps are same as Multi-disks test
        Discard test: Test discard off/unmap
        Cache test: Test cache.direct off/on
        Detect-zeroes test: Test detect_zeroes off/on/unmap
        Read-only test: Test read-only on
    """

    def _setup_vdpa_disks():
        for img in vdpa_blk_images:
            dev = vdpa_blk_test.add_dev(img)
            logger.debug("Add vhost device %s %s", img, dev)

    def _cleanup_vdpa_disks():
        for img in vdpa_blk_images:
            vdpa_blk_test.remove_dev(img)

    def _get_window_disk_index_by_serial(serial):
        idx_info = get_disk_props_by_serial_number(session, serial, ["Index"])
        if idx_info:
            return idx_info["Index"]
        test.fail("Not find expected disk %s" % serial)

    def _check_disk_in_guest(img):
        os_type = params["os_type"]
        logger.debug("Check disk %s in guest", img)
        if os_type == "windows":
            img_size = params.get("image_size_%s" % img)
            cmd = utils_misc.set_winutils_letter(session, guest_cmd)
            disk = _get_window_disk_index_by_serial(img)
            utils_disk.update_windows_disk_attributes(session, disk)
            logger.info("Clean disk:%s", disk)
            utils_disk.clean_partition_windows(session, disk)
            logger.info("Formatting disk:%s", disk)
            driver = utils_disk.configure_empty_disk(session, disk, img_size, os_type)[
                0
            ]
            output_path = driver + ":\\test.dat"
            cmd = cmd.format(output_path)
        else:
            output_path = get_linux_drive_path(session, img)
            cmd = guest_cmd.format(output_path)

        logger.debug(cmd)
        session.cmd(cmd)

    def multi_disks_test():
        for img in vdpa_blk_images:
            _check_disk_in_guest(img)

    def hotplug_unplug_test():
        plug = BlockDevicesPlug(vm)
        for img in vdpa_blk_images:
            plug.hotplug_devs_serial(img)
            _check_disk_in_guest(img)
            plug.unplug_devs_serial(img)

    def discard_test():
        for img in vdpa_blk_images:
            cmd = "blkdiscard -f %s && echo 'it works!' " % vdpa_blk_info[img]
            process.run(cmd, shell=True)

    logger = test.log
    vdpa_blk_test = None
    vdpa_blk_info = {}
    vm = None
    session = None
    expect_to_fail = params.get("expect_to_fail", "no")
    err_msg = params.get("err_msg", "unknown error")
    try:
        vdpa_blk_images = params["vdpa_sim_blk_images"].split()
        host_cmd = params.get("host_cmd")
        guest_cmd = params.get("guest_cmd")
        host_operation = params.get("host_operation")
        guest_operation = params.get("guest_operation")
        test_vm = params.get("test_vm", "no")

        logger.debug("Deploy VDPA blk env on host...")
        vdpa_blk_test = VhostVdpaBlkSimulatorTest()
        vdpa_blk_test.setup()

        logger.debug("Add VDPA blk disk on host...")
        _setup_vdpa_disks()

        locals_var = locals()
        if host_operation:
            logger.debug("Execute operation %s", host_operation)
            locals_var[host_operation]()

        logger.debug("Ready boot VM...")
        params["start_vm"] = "yes"
        login_timeout = params.get_numeric("login_timeout", 360)
        env_process.preprocess_vm(test, params, env, params.get("main_vm"))
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        session = vm.wait_for_login(timeout=login_timeout)

        if guest_operation:
            logger.debug("Execute guest operation %s", guest_operation)
            locals_var[guest_operation]()

        logger.debug("Destroy VM...")
        session.close()
        vm.destroy()
        vm = None
    except (virt_vm.VMCreateError, ShellCmdError) as e:
        logger.debug("Find exception %s", e)
        if expect_to_fail == "yes" and err_msg in e.output:
            logger.info("%s is expected ", err_msg)
            # reset expect_to_fail
            expect_to_fail = "no"
        else:
            raise exceptions.TestFail(e)
    finally:
        if vm:
            vm.destroy()

        _cleanup_vdpa_disks()

        if vdpa_blk_test:
            vdpa_blk_test.cleanup()

        if expect_to_fail != "no":
            raise exceptions.TestFail("Expected '%s' not happened" % err_msg)
