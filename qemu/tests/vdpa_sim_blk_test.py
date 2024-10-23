"""VDPA simulator blk test"""

from avocado.utils import process
from virttest import env_process, utils_disk, utils_misc
from virttest.utils_misc import get_linux_drive_path
from virttest.utils_windows.drive import get_disk_props_by_serial_number

from provider.block_devices_plug import BlockDevicesPlug
from provider.vdpa_sim_utils import VirtioVdpaBlkSimulatorTest


def run(test, params, env):
    """
    VDPA simulator blk test. It tests multiple scenarios:
    multi-disks,hotplug-unplug,and disk feature (discard)
    Multi-disks steps:
        1) Setup VDPA simulator ENV and add block devices.
        2) Simple IO test on host
        3) Boot VM with multi vdpa-blk disks
        4) Verify disk in guest
        5) Destroy VM
        6) Destroy vdpa-blk disk on host
        7. Destroy VDPA simulator ENV
    Hotplug-unplug test steps:
        1) Setup VDPA simulator ENV and add block devices.
        2) Simple IO test on host
        3) Boot VM
        4) Hotplug the vdpa-blk disks
        5) Verify disks in guest
        6) Unplug those vdpa-blk disks
        7) Destroy VM
        8) Destroy vdpa-blk disk on host
        9. Destroy VDPA simulator ENV
    Discard feature test steps:
        1) Setup VDPA simulator ENV and add block devices.
        2) Simple IO test on host
        3) blkdiscard operation on vdpa-blk disks
        4) Destroy vdpa-blk disk on host
        5. Destroy VDPA simulator ENV
    """

    def _setup_vdpa_disks():
        for img in vdpa_blk_images:
            dev = vdpa_blk_test.add_dev(img)
            vdpa_blk_info[img] = "/dev/%s" % dev
            params["image_name_%s" % img] = vdpa_blk_info[img]
            cmd = host_cmd.format(dev)
            process.run(cmd, shell=True)

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
            logger.info("Formatting disk:%s", disk)
            driver = utils_disk.configure_empty_disk(session, disk, img_size, os_type)[
                0
            ]
            output_path = driver + ":\\test.dat"
            cmd = cmd.format(output_path)
        else:
            output_path = get_linux_drive_path(session, img)
            cmd = guest_cmd.format(output_path, img)

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
    try:
        vdpa_blk_images = params["vdpa_sim_blk_images"].split()
        host_cmd = params["host_cmd"]
        guest_cmd = params["guest_cmd"]
        host_operation = params.get("host_operation")
        guest_operation = params.get("guest_operation")
        test_vm = params.get("test_vm", "no")

        logger.debug("Deploy VDPA blk env on host...")
        vdpa_blk_test = VirtioVdpaBlkSimulatorTest()
        vdpa_blk_test.setup()

        logger.debug("Add VDPA blk disk on host...")
        _setup_vdpa_disks()

        locals_var = locals()
        if host_operation:
            logger.debug("Execute operation %s", host_operation)
            locals_var[host_operation]()

        if test_vm == "yes":
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

        if test_vm == "yes":
            logger.debug("Destroy VM...")
            vm.destroy()
            vm = None

    finally:
        if vm:
            vm.destroy()

        _cleanup_vdpa_disks()

        if vdpa_blk_test:
            vdpa_blk_test.cleanup()
