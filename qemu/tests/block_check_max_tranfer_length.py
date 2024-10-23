import re

from virttest import error_context, utils_disk, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Check the maximum transfer length:

    1) Start guest with a data disk.
       Combined of seg_max and queue_depth.
    2) Do format disk in guest.
    3) Check the maximum transfer length.
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    img_size = params.get("image_size_stg", "10G")
    expect_max_transfer_length = params["expect_max_transfer_length"]
    vm = env.get_vm(params["main_vm"])
    session = vm.wait_for_login()

    check_cmd = utils_misc.set_winutils_letter(session, params["check_cmd"])
    error_context.context("Format data disk", test.log.info)
    disk_index = utils_disk.get_windows_disks_index(session, img_size)
    if not disk_index:
        test.error("Failed to get the disk index of size %s" % img_size)
    if not utils_disk.update_windows_disk_attributes(session, disk_index):
        test.error("Failed to enable data disk %s" % disk_index)
    drive_letter_list = utils_disk.configure_empty_windows_disk(
        session, disk_index[0], img_size
    )
    if not drive_letter_list:
        test.error("Failed to format the data disk")
    drive_letter = drive_letter_list[0]

    error_context.context(
        "Check the maximum transfer length if " "VIRTIO_BLK_F_SEG_MAX flag is on",
        test.log.info,
    )
    output = session.cmd_output(check_cmd % drive_letter)
    actual_max_transfer_length = re.findall(r"MaximumTransferLength: ([\w]+)", output)[
        0
    ]
    if actual_max_transfer_length != expect_max_transfer_length:
        test.error(
            "maximum transfer length %s is not expected" % actual_max_transfer_length
        )
