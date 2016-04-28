import logging

from autotest.client.shared import error

from virttest import utils_test
from virttest import utils_misc


@error.context_aware
def run(test, params, env):
    """
    Check physical block size and logical block size for virtio block device:
    1) Install guest with a new image.
    2) Verify whether physical/logical block size in guest is same as qemu
       parameters.
    TODO: This test only works on Linux guest, should make it work in windows
          guest. (Are there any windows tools to check block size?)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    name = params["main_vm"]
    if params.get("need_install") == "yes":
        error.context("Install guest with a new image", logging.info)
        utils_test.run_virt_sub_test(test, params, env,
                                     sub_type='unattended_install')
        params["cdroms"] = ""
        params["unattended_file"] = ""
        params["cdrom_unattended"] = ""
        params["kernel"] = ""
        params["initrd"] = ""
        params["kernel_params"] = ""
        params["boot_once"] = "c"
        vm = env.get_vm(name)
        vm.destroy()
        vm.create(params=params)

    vm = env.get_vm(name)
    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)

    try:
        # Get virtio block devices in guest.
        drive_serial = str(params["drive_serial_stg"])
        drive_path = utils_misc.get_linux_drive_path(session, drive_serial)
        if not drive_path:
            raise error.TestError("Could not find the specified"
                                  "virtio block device.")

        drive_kname = drive_path.split("/")[-1]
        expect_physical = int(params.get("physical_block_size_stg", 0))
        expect_logical = int(params.get("logical_block_size_stg", 0))
        error.context("Verify physical/Logical block size", logging.info)
        cmd = params.get("chk_phy_blk_cmd") % drive_kname
        logging.debug("Physical block size get via '%s'" % cmd)
        out_physical = int(session.cmd_output(cmd))
        cmd = params.get("chk_log_blk_cmd") % drive_kname
        logging.debug("Logical block size get via '%s'" % cmd)
        out_logical = int(session.cmd_output(cmd))
        if ((out_physical != expect_physical) or
                (out_logical != expect_logical)):
            msg = "Block size in guest doesn't match with qemu parameter\n"
            msg += "Physical block size in guest: %s, " % out_physical
            msg += "expect: %s" % expect_physical
            msg += "\nLogical block size in guest: %s, " % out_logical
            msg += "expect: %s" % expect_logical
            raise error.TestFail(msg)
    finally:
        if session:
            session.close()
