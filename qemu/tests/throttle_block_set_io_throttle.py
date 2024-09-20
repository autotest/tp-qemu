"""block_set_io_throttle testing on iothread enabled disk"""

import json
import time

from virttest import error_context, utils_disk, utils_misc
from virttest.utils_misc import get_linux_drive_path


# This decorator makes the test function aware of context strings
@error_context.context_aware
def run(test, params, env):
    """
    block_set_io_throttle testing on iothread enabled disk

    1) Boot vm with iothread enabled data disks.
    2) Login guest and start io on data disk.
    3) Execute block_set_io_throttle on data disks with different value.
    4) Verify vm still alive.
    """

    def _get_window_disk_index_by_serail(serial):
        cmd = "wmic diskdrive where SerialNumber='%s' get Index,Name"
        disks = session.cmd_output(cmd % serial)
        info = disks.splitlines()
        if len(info) > 1:
            attr = info[1].split()
            return attr[0]
        test.fail("Not find expected disk ")

    def _execute_set_io_throttle(monitor):
        cmd_qmp = params["cmd_qmp"]
        throttle_value = params["throttle_value"].split(",")
        images = params["data_images"].split()
        for repeat in range(params.get_numeric("repeat_times", 2)):
            for value in throttle_value:
                logger.info("Start %s block_set_io_throttle %s", repeat, value)
                for img in images:
                    dev = img
                    if params["drive_format_%s" % img] == "virtio":
                        dev = "/machine/peripheral/%s/virtio-backend" % img
                    cmd = cmd_qmp % (dev, value)
                    logger.info(cmd)
                    monitor.cmd_qmp("block_set_io_throttle", json.loads(cmd))
                time.sleep(3)

    logger = test.log
    os_type = params["os_type"]
    guest_cmd = params["guest_cmd"]
    disk_serial = params["image_stg1"]
    timeout = params.get_numeric("login_timeout", 360)
    error_context.context("Get the main VM", logger.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()
    qmp_monitor = vm.get_monitors_by_type("qmp")
    if qmp_monitor:
        qmp_monitor = qmp_monitor[0]
    else:
        test.error("Could not find a QMP monitor, aborting test")

    logger.info("Execute io in guest...")
    if os_type == "windows":
        img_size = params.get("image_size_stg1")
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

    logger.debug("Get output file path %s", output_path)
    guest_cmd = guest_cmd % output_path
    logger.debug("Ready to execute IO cmd:%s", guest_cmd)
    session.sendline(guest_cmd)
    logger.debug("Ready to execute_set_io_throttle")
    _execute_set_io_throttle(qmp_monitor)
    logger.debug("Verify the vm")
    session = vm.wait_for_login(timeout=timeout)
    vm.verify_alive()
    logger.debug("End of test")
