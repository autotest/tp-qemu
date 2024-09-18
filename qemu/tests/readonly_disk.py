from virttest import env_process, error_context, utils_disk, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    KVM reboot test:
    1) Log into a guest with virtio data disk
    2) Format the disk and copy file to it
    3) Stop the guest and boot up it again with the data disk set to readonly
    4) Try to copy file to the data disk
    5) Try to copy file from the data disk

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    error_context.context("TEST STEPS 1: Try to log into guest.", test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    error_context.context(
        "TEST STEPS 2: Format the disk and copy file to it", test.log.info
    )
    os_type = params["os_type"]
    copy_cmd = params.get("copy_cmd", "copy %s %s")
    fstype = params.get("fstype", "ntfs")
    data_image_size = params.get("image_size_data", "1G")
    data_image_num = int(
        params.get("data_image_num", len(params.objects("images")) - 1)
    )
    error_context.context(
        "Get windows disk index that to " "be formatted", test.log.info
    )
    disk_index_list = utils_disk.get_windows_disks_index(session, data_image_size)
    if len(disk_index_list) < data_image_num:
        test.fail(
            "Fail to list all data disks. "
            "Set disk number: %d, "
            "get disk number in guest: %d." % (data_image_num, len(disk_index_list))
        )
    src_file = utils_misc.set_winutils_letter(
        session, params["src_file"], label="WIN_UTILS"
    )
    error_context.context(
        "Clear readonly for all disks and online " "them in guest.", test.log.info
    )
    if not utils_disk.update_windows_disk_attributes(session, disk_index_list):
        test.fail("Failed to update windows disk attributes.")
    error_context.context(
        "Format disk %s in guest." % disk_index_list[0], test.log.info
    )
    drive_letter = utils_disk.configure_empty_disk(
        session, disk_index_list[0], data_image_size, os_type, fstype=fstype
    )
    if not drive_letter:
        test.fail("Fail to format disks.")
    dst_file = params["dst_file"] % drive_letter[0]
    session.cmd(copy_cmd % (src_file, dst_file))

    msg = "TEST STEPS 3: Stop the guest and boot up again with the data disk"
    msg += " set to readonly"
    error_context.context(msg, test.log.info)
    session.close()
    vm.destroy()

    data_img = params.get("images").split()[-1]
    params["image_readonly_%s" % data_img] = "yes"
    params["force_create_image_%s" % data_img] = "no"
    env_process.preprocess(test, params, env)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=timeout)

    error_context.context(
        "TEST STEPS 4: Write to the readonly disk expect:"
        "The media is write protected",
        test.log.info,
    )
    dst_file_readonly = params["dst_file_readonly"] % drive_letter[0]
    o = session.cmd_output(copy_cmd % (src_file, dst_file_readonly))
    if not o.find("write protect"):
        test.fail("Write in readonly disk should failed\n. {}".format(o))

    error_context.context(
        "TEST STEPS 5: Try to read from the readonly disk", test.log.info
    )
    s, o = session.cmd_status_output(copy_cmd % (dst_file, r"C:\\"))
    if s != 0:
        test.fail("Read file failed\n. {}".format(o))

    session.close()
