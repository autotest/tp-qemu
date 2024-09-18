"""
Check_coredump
This is a kind of post check case in a test loop.
"""

import glob
import logging
import os
import time

import virttest.utils_libguestfs as lgf
from avocado.utils import path as utils_path
from virttest import data_dir, error_context, utils_misc

LOG_JOB = logging.getLogger("avocado.test")


def get_images():
    """
    Find the image names under the image directory

    :return: image names
    """
    return glob.glob(utils_misc.get_path(data_dir.get_data_dir(), "images/*.*"))


def coredump_exists(mntpnt, files, out_dir):
    """
    Check if there is specified file in the image
    If hit the files, copy them to output_dir
    The out_dir is the directory contains debug log

    :param mntpnt: The mountpoint on the host
    :param files: The files pattern need be checked
    :param out_dir: If found coredump files, copy them
                    to the directory
    :return: Format as Bool, List which contains tuples
             If the checked file exists,
             return True, [("checked_file_name", "file_created_time")]
             If not, return False, []
    """
    file_exists = False
    msgs_return = []

    for chk_file in files:
        file_need_check = utils_misc.get_path(mntpnt, chk_file)
        files_glob = glob.glob(file_need_check)
        if files_glob:
            file_exists = True
            for item in files_glob:
                file_ctime = time.ctime(os.path.getctime(item))
                msgs_return.append((os.path.basename(item), file_ctime))
                error_context.context(
                    "copy files %s %s" % (item, out_dir), LOG_JOB.info
                )
                os.system("cp -rf %s %s" % (item, out_dir))

    return file_exists, msgs_return


def check_images_coredump(image, mntpnt, check_files, debugdir):
    """
    Mount the images and check the coredump files

    :return: Format as Bool, List
             If the checked file exists
                 return True, ["checked file name"]
             If not, return False []
    """

    found_coredump = False
    msgs_return = []

    try:
        error_context.context(
            "Mount the guest image %s to host mount point" % image, LOG_JOB.info
        )
        status = lgf.guestmount(image, mntpnt, True, True, debug=True, is_disk=True)
        if status.exit_status:
            msgs_return.append("Could not mount guest image %s." % image)
            error_context.context(msgs_return[0], LOG_JOB.error)
        else:
            found_coredump, msgs_return = coredump_exists(mntpnt, check_files, debugdir)
    finally:
        if os.path.ismount(mntpnt):
            error_context.context("guestunmount host mount point")
            lgf.lgf_command("guestunmount %s" % mntpnt)

    return found_coredump, msgs_return


def format_report(results):
    """
    Format the report as below table.
     Header
     +-------------------------------------+
     |image name (line)                    |
     +-------------------------------------+
     |  |crash file(subline) | timestamp   |
     +--+--------------------+-------------+
     |  |...                 | ...         |
     +--+--------------------+-------------+

    :return: the table messages formatted as above
    :results: the parameter transfered into
              image, msg_list
    """

    line_break = "\n"
    table_header = "Coredump file exists in the images:"
    lines = []
    sublines = []

    for image, chk_msg in results:
        lines += [image]

        if isinstance(chk_msg, list):
            for fname, ftime in chk_msg:
                sublines += [fname + ", " + ftime]

        lines += ["\t" + subline for subline in sublines]

    all_lines = [""] + [table_header] + lines + [""]

    return line_break.join(all_lines)


@error_context.context_aware
def run(test, params, env):
    """
    We find out that sometimes the guest crashed between two
    cases in a loop.  For example:
    1. case A executed the steps and finished with good.
    2. the post process do some check, pause or shutdown
       operates.
    3. guest crashed and reboot or just quit(But the case
       already finished with good).
    4. case B start and also didn't get the guest crashed
       status.

    Check if there is any core dump file in guest image .

    1) Check all the existing guest images in the image directory.
    2) Mount guest image on the host.
    3) Check "C:\\windows\\dump" for Windows and core file for Linux.
    4) If yes, copy them to working directory.
    """

    # Preliminary
    # yum install libguestfs libguestfs-tools libguestfs-winsupport
    try:
        utils_path.find_command("guestmount")
    except:
        warn_msg = (
            "Need packages: libguestfs libguestfs-tools" + " libguestfs-winsupport"
        )
        test.cancel(warn_msg)

    # define the file name need to be checked
    file_check_win_default = "Windows/dump"
    file_check_linux_default = "var/crash/*"
    host_mountpoint_default = "mnt/mountpoint"

    host_mountpoint = params.get("host_mountpoint", host_mountpoint_default)
    host_mountpoint = utils_misc.get_path(test.debugdir, host_mountpoint)
    file_chk_for_win = params.get("coredump_check_win", file_check_win_default)
    file_chk_for_linux = params.get("coredump_check_linux", file_check_linux_default)

    # check if the host_mountpoint exists.
    if not (os.path.isdir(host_mountpoint) and os.path.exists(host_mountpoint)):
        os.makedirs(host_mountpoint)

    coredump_file_exists = False
    check_files = [file_chk_for_win, file_chk_for_linux]
    check_results = []

    error_context.context("Get all the images name", test.log.info)
    images = get_images()
    error_context.context("images: %s" % images, test.log.info)

    # find all the images
    # mount per-image to check if the dump file exists
    error_context.context("Check coredump file per-image", test.log.info)
    for image in images:
        status, chk_msgs = check_images_coredump(
            image, host_mountpoint, check_files, test.debugdir
        )
        coredump_file_exists = coredump_file_exists or status
        if status:
            check_results.append((image, chk_msgs))

    # if found, report the result
    if coredump_file_exists:
        report_msg = format_report(check_results)
        test.fail(report_msg)
