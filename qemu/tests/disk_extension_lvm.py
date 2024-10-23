"""continually disk extension on lvm backend"""

import threading
import time

from avocado.utils import process
from virttest import error_context, utils_disk, utils_misc, utils_test
from virttest.utils_misc import get_linux_drive_path


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    QEMU 'disk images extension on lvm in io-error status' test

    1) Create small size lvm on large vg size.
    2) Create qcow2 image based on the lvm
    3) Boot vm with the lvm as vm data disk
    4) Execute large size io on the data disk.
    5) The vm will step in pause status due to no enough disk space.
    6) Start to periodic increase lvm disk size(128M) at first pause.
    7) Increase disk size when vm step in pause and resume vm.
    8) Repeat step 7 until final disk size exceed max size (50G)


    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _get_window_disk_index_by_serail(serial):
        cmd = "wmic diskdrive where SerialNumber='%s' get Index,Name"
        disks = session.cmd_output(cmd % serial)
        info = disks.splitlines()
        if len(info) > 1:
            attr = info[1].split()
            return attr[0]
        test.fail("Not find expected disk ")

    def _get_free_size():
        cmd = "df /home -BG|tail -n 1|awk '{print $4}'|tr -d 'G'"
        return int(process.system_output(cmd, shell=True))

    def _extend_lvm(size):
        process.system_output(extend_lvm_command % size, shell=True)

    def _get_lvm_size():
        return float(process.system_output(get_lvm_size_command, shell=True))

    def _extend_lvm_daemon():
        while _get_lvm_size() < disk_size:
            test.log.debug("periodical extension.")
            _extend_lvm("128M")
            time.sleep(5)

    disk_size = int(params["disk_size"][0:-1])
    timeout = int(params.get("login_timeout", 360))
    wait_timeout = int(params.get("wait_timeout", 360))
    os_type = params["os_type"]
    driver_name = params.get("driver_name")
    disk_serial = params["disk_serial"]
    guest_cmd = params["guest_cmd"]
    extend_lvm_command = params["extend_lvm_command"]
    get_lvm_size_command = params["get_lvm_size_command"]
    free_size = int(params["free_size"][0:-1])

    if _get_free_size() < free_size:
        test.cancel(
            "No enough space to run this case %d %d" % (_get_free_size(), free_size)
        )

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=timeout)
    if os_type == "windows" and driver_name:
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name, timeout
        )

    if os_type == "windows":
        img_size = params["disk_size"]
        guest_cmd = utils_misc.set_winutils_letter(session, guest_cmd)
        disk = _get_window_disk_index_by_serail(disk_serial)
        utils_disk.update_windows_disk_attributes(session, disk)
        test.log.info("Formatting disk:%s", disk)
        driver = utils_disk.configure_empty_disk(session, disk, img_size, os_type)[0]
        output_path = driver + ":\\test.dat"
    else:
        output_path = get_linux_drive_path(session, disk_serial)

    if not output_path:
        test.fail("Can not get output file path in guest.")

    test.log.debug("Get output file path %s", output_path)
    guest_cmd = guest_cmd % output_path
    session.sendline(guest_cmd)

    test.assertTrue(vm.wait_for_status("paused", wait_timeout))
    thread = threading.Thread(target=_extend_lvm_daemon)
    thread.start()
    while _get_lvm_size() < disk_size:
        if vm.is_paused():
            test.log.debug("pause extension.")
            _extend_lvm("500M")
            vm.monitor.cmd("cont")

            # Verify the guest status
            if _get_lvm_size() < disk_size:
                try:
                    test.assertTrue(vm.wait_for_status("paused", wait_timeout))
                except AssertionError:
                    if _get_lvm_size() < disk_size:
                        raise
                    else:
                        test.log.debug("Ignore timeout.")
            else:
                test.assertTrue(vm.wait_for_status("running", wait_timeout))
        else:
            time.sleep(0.1)
