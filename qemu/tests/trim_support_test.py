import os
import time

from avocado.utils import process
from virttest import data_dir, error_context, utils_disk, utils_misc, utils_test

from provider import win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    Test disk trimming in windows guest
    1) boot the vm with a data disk
    2) format the data disk without quick mode
    3) check the disk file size in host, and record for compare
    4) trim the data disk in guest
    5) check the disk file again in host, the file size should shrink

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _get_size_value(size_str):
        """
        Get size value form size string

        :param size_str: data size string
        :return: the size numeric value, measured by MB
        """
        size_str = utils_misc.normalize_data_size(size_str)
        size = float(size_str)
        return size

    def _disk_size_smaller(ori_size):
        """
        Check till the disk size becomes smaller than ori_size
        :param ori_size: original size to compare to
        :return: new size if it smaller than ori_size, else None
        """
        output = process.system_output(host_check_cmd, shell=True).decode()
        new_size = _get_size_value(str(output))
        test.log.info("Current data disk size: %sMB", new_size)
        if new_size < ori_size:
            return new_size
        return None

    def query_system_events(filter_options):
        """Query the system events in filter options."""
        test.log.info("Query the system event log.")
        cmd = params.get("query_cmd") % filter_options
        return params.get("searched_keywords") in session.cmd(cmd).strip()

    host_check_cmd = params.get("host_check_cmd")
    image_dir = os.path.join(data_dir.get_data_dir(), "images")
    host_check_cmd = host_check_cmd % (image_dir, params["image_format"])
    image_name = params["stg_name"]
    stg_param = params.object_params(image_name)
    image_size_str = stg_param["image_size"]
    guest_trim_cmd = params["guest_trim_cmd"]
    driver_verifier = params["driver_verifier"]
    event_id = params.get("event_id")

    timeout = float(params.get("timeout", 360))
    defrag_timeout = params.get_numeric("defrag_timeout", 600, float)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=timeout)
    error_context.context(
        "Check if the driver is installed and verified", test.log.info
    )
    session = utils_test.qemu.windrv_check_running_verifier(
        session, vm, test, driver_verifier, timeout
    )

    error_context.context("Format data disk", test.log.info)
    disk_index = utils_misc.wait_for(
        lambda: utils_disk.get_windows_disks_index(session, image_size_str), 120
    )
    if not disk_index:
        test.error("Failed to get the disk index of size %s" % image_size_str)
    if not utils_disk.update_windows_disk_attributes(session, disk_index):
        test.error("Failed to enable data disk %s" % disk_index)
    drive_letter_list = utils_disk.configure_empty_windows_disk(
        session, disk_index[0], image_size_str, quick_format=False
    )
    if not drive_letter_list:
        test.error("Failed to format the data disk")
    drive_letter = drive_letter_list[0]

    error_context.context("Check size from host before disk trimming")
    output = process.system_output(host_check_cmd, shell=True).decode()
    ori_size = _get_size_value(output)
    test.log.info("Data disk size: %sMB", ori_size)

    error_context.context("Trim data disk in guest")
    status, output = session.cmd_status_output(
        guest_trim_cmd % drive_letter, timeout=defrag_timeout
    )
    if status:
        test.error(
            "Error when trim the volume, status=%s, output=%s" % (status, output)
        )
    if event_id:
        time.sleep(10)
        session = vm.reboot(session)
        if query_system_events(params["filter_options"]):
            test.fail("Disk corruption after trim for %s" % params.get("block_size"))

    if params["retrim_size_check"] == "yes":
        error_context.context("Check size from host after disk trimming")
        new_size = utils_misc.wait_for(lambda: _disk_size_smaller(ori_size), 20, 10, 1)

        if new_size is None:
            test.error("Data disk size is not smaller than: %sMB" % ori_size)

    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if params.get("memory_leak_check", "no") == "yes":
        win_driver_utils.memory_leak_check(vm, test, params)
