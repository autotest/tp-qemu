import logging
from virttest import utils_misc
from virttest import error_context
from avocado.core import exceptions


@error_context.context_aware
def run(test, params, env):
    """
    Copy file between block disk and scsi disk:
    1) Boot guest with both block disk and scsi disk attached.
    2) Get disk dev file name in guest
    3) Format those disks in guest
    4) Copy/dd file to disk0
    5) Copy file from disk0 to disk1
    6) Check md5sum of file after copy
    7) Copy file from disk1 to disk0
    8) Check md5sum of file after copy

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    def copy_files(session, src_disk, dst_disk):
        """
         Copy file from src_disk to dst_disk in guest
        :param session: VM session
        :param src_disk: the src disk
        :param dst_disk: the dst disk
        """
        copy_cmd = params["copy_cmd"]
        file_name = params["file_name"]
        copy_timeout = int(params.get("copy_timeout", 360))

        src_file = "".join([src_disk, file_name])
        dst_file = "".join([dst_disk, file_name])
        error_context.context("Copy file from %s to %s"
                              % (src_disk, dst_disk), logging.info)
        copy_cmd = copy_cmd % (src_file, dst_file)
        session.cmd_status(copy_cmd, timeout=copy_timeout)

        md5sum_src = session.cmd_status(params["md5sum_cmd"] % src_file)
        md5sum_dst = session.cmd_status(params["md5sum_cmd"] % dst_file)
        if md5sum_src != md5sum_dst:
            raise exceptions.TestFail("File md5sum is changed after copy")

    cmd_timeout = int(params.get("cmd_timeout", 360))
    login_timeout = int(params.get("login_timeout", 360))
    os_type = params["os_type"]

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=login_timeout)

    guest_dev = utils_misc.get_linux_disks(session, parted=False).keys()
    disks_did = params.get("disk_index", guest_dev)
    disks_list = []
    for did in disks_did:
        disk = utils_misc.format_guest_disk(session, os_type, did)
        disks_list.append(disk)
    error_context.context("Get disks name in guest", logging.info)
    try:
        error_context.context("Generate file to disks0", logging.info)
        if params.get("dd_cmd"):
            session.cmd(params.get("dd_cmd") % disks_list[0],
                        timeout=cmd_timeout)
        else:
            win_vol = utils_misc.get_winutils_vol(session)
            if win_vol:
                win_vol = "".join([win_vol, ":"])
            else:
                raise exceptions.TestFail("Didn't find winutils volume")
            copy_files(session, win_vol, disks_list[0])
        for i in xrange(int(params.get("repeat_times", 1))):
            copy_files(session, disks_list[0], disks_list[1])
            copy_files(session, disks_list[1], disks_list[0])
    finally:
        if os_type == "linux":
            try:
                for disk in disks_list:
                    logging.info("umount %s" % disk)
                    session.cmd("umount %s" % disk)
                    logging.info("Clean test folders")
                    session.cmd("rm -rf %s" % disk)
            except Exception:
                pass
        if session:
            session.close()
