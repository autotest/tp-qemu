"""Test to kill vm should non-infinite"""

import random
import string
import time

from avocado.utils import process
from virttest import data_dir, env_process, utils_misc
from virttest.iscsi import Iscsi
from virttest.utils_misc import get_linux_drive_path


def run(test, params, env):
    """
    When VM encounter fault disk result in it loss response.
    The kill vm should non-infinite.

    Steps:
        1) Emulate fault disk with dmsetup and iscsi.
        2) Boot vm with the pass-through disk.
        3) Login guest and do io on the disk.
        4) Kill the qemu process and wait it truly be killed.
        5) Check the kill time it should less than expected timeout.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def _prepare_fault_disk():
        cmd = params["cmd_get_scsi_debug"]
        process.run(cmd, shell=True)
        cmd = "cat " + params["dev_scsi_debug"]
        params["scsi_debug_disk"] = process.getoutput(cmd, shell=True)
        if not params["scsi_debug_disk"]:
            test.fail("Can not find scsi_debug disk %s" % cmd)

        cmd_dmsetup = params["cmd_dmsetup"].format(
            params["dev_mapper"], params["scsi_debug_disk"]
        )
        process.run(cmd_dmsetup, shell=True)

        cmd = "dmsetup info " + params["dev_mapper"]
        process.run(cmd, shell=True)
        params["mapper_disk"] = "/dev/mapper/" + params["dev_mapper"]
        params["emulated_image"] = params["mapper_disk"]

    def _cleanup():
        if vm and vm.is_alive():
            vm.destroy()
        if params["mapper_disk"]:
            cmd_cleanup = params["cmd_cleanup"]
            process.run(cmd_cleanup, 600, shell=True)

    def _online_disk_windows(index):
        disk = "disk_" + "".join(random.sample(string.ascii_letters + string.digits, 4))
        online_cmd = "echo select disk %s > " + disk
        online_cmd += " && echo online disk noerr >> " + disk
        online_cmd += " && echo clean >> " + disk
        online_cmd += " && echo attributes disk clear readonly >> " + disk
        online_cmd += " && echo detail disk >> " + disk
        online_cmd += " && diskpart /s " + disk
        online_cmd += " && del /f " + disk
        return session.cmd(online_cmd % index, timeout=timeout)

    def _get_window_disk_index_by_uid(wwn):
        cmd = 'powershell -command "get-disk|?'
        cmd += " {$_.UniqueId -eq '%s'}|select number|FL\"" % wwn
        status, output = session.cmd_status_output(cmd)
        if status != 0:
            test.fail("execute command fail: %s" % output)
        test.log.debug(output)
        output = "".join([s for s in output.splitlines(True) if s.strip()])

        info = output.split(":")
        if len(info) > 1:
            return info[1].strip()

        cmd = 'powershell -command "get-disk| FL"'
        output = session.cmd_output(cmd)
        test.log.debug(output)
        test.fail("Not find expected disk:" + wwn)

    def _get_disk_wwn(devname):
        cmd = "lsblk -ndo WWN " + devname
        output = process.system_output(cmd, shell=True).decode()
        wwn = output.replace("0x", "")
        return wwn

    vm = None
    iscsi = None
    params["scsi_debug_disk"] = None
    params["mapper_disk"] = None
    timeout = params.get_numeric("timeout", 360)
    kill_max_timeout = params.get_numeric("kill_max_timeout", 240)
    kill_min_timeout = params.get_numeric("kill_min_timeout", 60)
    os_type = params["os_type"]
    guest_cmd = params["guest_cmd"]
    host_kill_command = params["host_kill_command"]

    try:
        test.log.info("Prepare fault disk.")
        _prepare_fault_disk()
        test.log.info("Create iscsi disk disk.")
        base_dir = data_dir.get_data_dir()
        iscsi = Iscsi.create_iSCSI(params, base_dir)
        iscsi.login()

        dev_name = utils_misc.wait_for(lambda: iscsi.get_device_name(), 60)
        if not dev_name:
            test.error("Can not get the iSCSI device.")

        test.log.info("Create host disk %s", dev_name)
        disk_wwn = _get_disk_wwn(dev_name)
        params["image_name_stg0"] = dev_name

        test.log.info("Booting vm...")
        params["start_vm"] = "yes"
        vm = env.get_vm(params["main_vm"])
        env_process.process(
            test, params, env, env_process.preprocess_image, env_process.preprocess_vm
        )
        session = vm.wait_for_login(timeout=600)

        if os_type == "windows":
            guest_cmd = utils_misc.set_winutils_letter(session, guest_cmd)
            disk_drive = _get_window_disk_index_by_uid(disk_wwn)
            _online_disk_windows(disk_drive)
        else:
            disk_drive = get_linux_drive_path(session, disk_wwn)

        guest_cmd = guest_cmd % disk_drive
        test.log.debug("guest_cmd:%s", guest_cmd)

        test.log.info("Execute io in guest...")
        session.sendline(guest_cmd)
        time.sleep(10)

        test.log.info("Ready to kill vm...")
        process.system_output(host_kill_command, shell=True).decode()

        real_timeout = int(
            process.system_output(params["get_timeout_command"], shell=True).decode()
        )

        if kill_min_timeout < real_timeout < kill_max_timeout:
            test.log.info("Succeed kill timeout: %d", real_timeout)
        else:
            test.fail(
                "Kill timeout %d not in range (%d , %d)"
                % (real_timeout, kill_min_timeout, kill_max_timeout)
            )
        vm = None
    finally:
        test.log.info("cleanup")
        if iscsi:
            iscsi.cleanup()
        _cleanup()
