"""Test serial length"""

from virttest import error_context
from virttest.utils_misc import get_linux_drive_path


@error_context.context_aware
def run(test, params, env):
    """
    Test serial length

    Steps:
        1. Boot vm with long length serial or device_id on data disks
        (length great than 32 characters)
        2. login guest check the serial or uid should keep same

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _find_disks_by_serial():
        """
        Find the disk name by image serial in guest.
        """
        wrong_disks = []
        for img in images:
            image_params = params.object_params(img)
            serial = image_params["image_serial"]
            test.log.info("Try to Find the image %s by %s", img, serial)
            os_type = params["os_type"]
            cmd = params["cmd_get_disk_id"]
            if os_type == "windows":
                cmd = cmd.format(serial)
                status, output = session.cmd_status_output(cmd)
                if status != 0:
                    test.fail("Execute command fail: %s" % output)
                disk = output.strip()
            else:
                disk = get_linux_drive_path(session, serial)
                if disk:
                    tmp_file = "/tmp/%s.vpd" % img
                    cmd = cmd.format(disk, tmp_file, serial)
                    status, output = session.cmd_status_output(cmd)
                    if status != 0:
                        test.log.error("Check %s vpd fail: %s", disk, output)
                        disk = ""

            if len(disk) > 4:
                test.log.info("Find disk %s %s ", img, disk)
            else:
                wrong_disks.append(img)

        if len(wrong_disks):
            test.fail("Can not get disks %s by serial or uid" % wrong_disks)

    images = params["data_images"].split()
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    _find_disks_by_serial()
