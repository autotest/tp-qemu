import re

import aexpect
from virttest import error_context, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Format guest disk:
    1) Boot guest with second disk
    2) Login to the guest
    3) Get disk list in guest
    4) Create partition on disk
    5) Format the disk
    6) Mount the disk
    7) Read in the file to see whether content has changed
    8) Umount the disk (Optional)
    9) Check dmesg output in guest (Optional)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Login to the guest", test.log.info)
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 360)))
    cmd_timeout = int(params.get("cmd_timeout", 360))
    os_type = params["os_type"]

    if os_type == "linux":
        dmesg_cmd = params.get("dmesg_cmd", "dmesg -C")
        session.cmd(dmesg_cmd)

    drive_path = ""
    if os_type == "linux":
        drive_name = params.objects("images")[-1]
        drive_id = params["blk_extra_params_%s" % drive_name].split("=")[1]
        # If a device option(bool/str) in qemu cmd line doesn't have a value,
        # qemu assigns the value as "on".
        if drive_id == "NO_EQUAL_STRING":
            drive_id = "on"
        elif drive_id == "EMPTY_STRING":
            drive_id = ""
        drive_path = utils_misc.get_linux_drive_path(session, drive_id)
        if not drive_path:
            test.error("Failed to get '%s' drive path" % drive_name)

    # Create a partition on disk
    create_partition_cmd = params.get("create_partition_cmd")
    if create_partition_cmd:
        has_dispart = re.findall("diskpart", create_partition_cmd, re.I)
        if os_type == "windows" and has_dispart:
            error_context.context("Get disk list in guest")
            list_disk_cmd = params.get("list_disk_cmd")
            status, output = session.cmd_status_output(
                list_disk_cmd, timeout=cmd_timeout
            )
            for i in re.findall(r"Disk*.(\d+)\s+Offline", output):
                error_context.context(
                    "Set disk '%s' to online status" % i, test.log.info
                )
                set_online_cmd = params.get("set_online_cmd") % i
                status, output = session.cmd_status_output(
                    set_online_cmd, timeout=cmd_timeout
                )
                if status != 0:
                    test.fail("Can not set disk online %s" % output)

        error_context.context("Create partition on disk", test.log.info)
        status, output = session.cmd_status_output(
            create_partition_cmd, timeout=cmd_timeout
        )
        if status != 0:
            test.fail("Failed to create partition with error: %s" % output)

    format_cmd = params.get("format_cmd", "").format(drive_path)
    if format_cmd:
        if os_type == "linux":
            show_mount_cmd = params["show_mount_cmd"].format(drive_path)
            status = session.cmd_status(show_mount_cmd)
            if not status:
                error_context.context("Umount before format", test.log.info)
                umount_cmd = params["umount_cmd"].format(drive_path)
                status, output = session.cmd_status_output(
                    umount_cmd, timeout=cmd_timeout
                )
                if status != 0:
                    test.fail("Failed to umount with error: %s" % output)
            error_context.context("Wipe existing filesystem", test.log.info)
            wipefs_cmd = params["wipefs_cmd"].format(drive_path)
            session.cmd(wipefs_cmd)
        error_context.context(
            "Format the disk with cmd '%s'" % format_cmd, test.log.info
        )
        status, output = session.cmd_status_output(format_cmd, timeout=cmd_timeout)
        if status != 0:
            test.fail("Failed to format with error: %s" % output)

    mount_cmd = params.get("mount_cmd", "").format(drive_path)
    if mount_cmd:
        error_context.context("Mount the disk with cmd '%s'" % mount_cmd, test.log.info)
        status, output = session.cmd_status_output(mount_cmd, timeout=cmd_timeout)
        if status != 0:
            show_dev_cmd = params.get("show_dev_cmd", "").format(drive_path)
            device_list = session.cmd_output_safe(show_dev_cmd)
            test.log.debug("The devices which will be mounted are: %s", device_list)
            test.fail("Failed to mount with error: %s" % output)

    testfile_name = params.get("testfile_name")
    if testfile_name:
        error_context.context("Write some random string to test file", test.log.info)
        ranstr = utils_misc.generate_random_string(100)

        writefile_cmd = params["writefile_cmd"]
        writefile_cmd = writefile_cmd % (ranstr, testfile_name)
        status, output = session.cmd_status_output(writefile_cmd, timeout=cmd_timeout)
        if status != 0:
            test.fail("Write to file error: %s" % output)

        error_context.context(
            "Read in the file to see whether " "content has changed", test.log.info
        )
        md5chk_cmd = params.get("md5chk_cmd")
        if md5chk_cmd:
            status, output = session.cmd_status_output(md5chk_cmd, timeout=cmd_timeout)
            if status != 0:
                test.fail("Check file md5sum error.")

        readfile_cmd = params["readfile_cmd"]
        readfile_cmd = readfile_cmd % testfile_name
        status, output = session.cmd_status_output(readfile_cmd, timeout=cmd_timeout)
        if status != 0:
            test.fail("Read file error: %s" % output)
        if output.strip() != ranstr:
            test.fail(
                "The content written to file has changed, "
                "from: %s, to: %s" % (ranstr, output.strip())
            )

    umount_cmd = params.get("umount_cmd", "").format(drive_path)
    if umount_cmd:
        error_context.context("Unmounting disk(s) after file " "write/read operation")
        status, output = session.cmd_status_output(umount_cmd, timeout=cmd_timeout)
        if status != 0:
            show_mount_cmd = params.get("show_mount_cmd", "").format(drive_path)
            mount_list = session.cmd_output_safe(show_mount_cmd)
            test.log.debug("The mounted devices are: %s", mount_list)
            test.fail("Failed to umount with error: %s" % output)

    # Clean partition on disk
    clean_partition_cmd = params.get("clean_partition_cmd")
    if clean_partition_cmd:
        status, output = session.cmd_status_output(
            clean_partition_cmd, timeout=cmd_timeout
        )
        if status != 0:
            test.fail("Failed to clean partition with error: %s" % output)

    output = ""
    try:
        output = session.cmd("dmesg -c")
        error_context.context("Checking if there are I/O error " "messages in dmesg")
    except aexpect.ShellCmdError:
        pass

    io_error_msg = []
    for line in output.splitlines():
        if "Buffer I/O error" in line:
            io_error_msg.append(line)
        if re.search(r"reset \w+ speed USB device", line):
            io_error_msg.append(line)

    if io_error_msg:
        e_msg = "IO error found on guest's dmesg when formatting USB device"
        test.log.error(e_msg)
        for line in io_error_msg:
            test.log.error(line)
        test.fail(e_msg)

    session.close()
