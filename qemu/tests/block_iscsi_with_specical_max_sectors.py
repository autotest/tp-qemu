"""Test IO on specific max_sector_kb of disk"""

import logging

from avocado.utils import process
from virttest import data_dir, env_process, utils_misc
from virttest.iscsi import Iscsi
from virttest.utils_misc import get_linux_drive_path


def run(test, params, env):
    """
    Test IO on specific max_sector_kb of disk.

    Steps:
        1) Create lvs based on iscsi disk with specific max_sector_kb.
        2) Boot vm with the lvs disks.
        3) Login guest and do io on the disks.
        4) Wait minutes then Check the VM still running.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def _setup_lvs(dev):
        cmd = params["cmd_set_max_sector"].format(dev.replace("/dev/", ""))
        process.run(cmd, shell=True)
        cmd = params["cmd_setup_vg"].format(dev)
        process.run(cmd, shell=True)
        for lv in lvs:
            cmd = params["cmd_setup_lv"].format(lv)
            process.run(cmd, shell=True)
            cmd = params["cmd_build_img"].format(lv)
            process.run(cmd, shell=True)

    def _cleanup_lvs(dev):
        if vm and vm.is_alive():
            vm.destroy()

        if not dev:
            return

        cmd = params["cmd_clean_lv"]
        process.run(cmd, shell=True)
        cmd = params["cmd_clean_vg"].format(dev)
        process.run(cmd, shell=True)

    def _execute_io_in_guest():
        all_cmd = []
        for serial in lvs:
            drive = get_linux_drive_path(session, serial)
            cmd = guest_cmd.format(drive)
            all_cmd.append(cmd)

        for cmd in all_cmd:
            log.info("Run io in guest: %s", cmd)
            dd_session = vm.wait_for_login(timeout=timeout)
            dd_session.sendline(cmd)

    vm = None
    iscsi = None
    dev_name = None
    log = logging.getLogger("avocado.test")
    lvs = params["lvs_name"].split(",")
    timeout = params.get_numeric("timeout", 180)
    guest_cmd = params["guest_cmd"]

    try:
        params["image_size"] = params["emulated_image_size"]
        log.info("Create iscsi disk.")
        base_dir = data_dir.get_data_dir()
        iscsi = Iscsi.create_iSCSI(params, base_dir)
        iscsi.login()

        dev_name = utils_misc.wait_for(lambda: iscsi.get_device_name(), 60)
        if not dev_name:
            test.error("Can not get the iSCSI device.")

        log.info("Prepare lvs disks on %s", dev_name)
        _setup_lvs(dev_name)

        log.info("Booting vm...")
        params["start_vm"] = "yes"
        vm = env.get_vm(params["main_vm"])
        env_process.process(
            test, params, env, env_process.preprocess_image, env_process.preprocess_vm
        )
        session = vm.wait_for_login(timeout=timeout)

        log.info("Execute IO in guest ...")
        _execute_io_in_guest()
        log.info("Check guest status.")
        if utils_misc.wait_for(
            lambda: not vm.monitor.verify_status("running"), 600, first=10, step=20
        ):
            if vm.is_dead():
                test.fail("Vm in dead status.")

            test.fail("VM not in running: %s" % vm.monitor.get_status())

    finally:
        log.info("cleanup")
        _cleanup_lvs(dev_name)
        if iscsi:
            iscsi.cleanup()
