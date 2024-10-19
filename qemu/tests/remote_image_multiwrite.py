import re

from virttest import error_context, utils_disk, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    1) Start guest with both data disk and system disk.
    2) Format a data disk(ext4 for rhel6+ and xfs for rhel7+)

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    session = None
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=int(params.get("login_timeout", 240)))

    stg_tag = params["images"].split()[-1]
    stg_params = params.object_params(stg_tag)
    stg_fstype = stg_params["disk_format"]
    stg_size = stg_params["image_size"]
    stg_extra_params = stg_params.get("blk_extra_params", "")
    match = re.search(r"(serial|wwn)=(\w+)", stg_extra_params, re.M)

    try:
        drive_id = match.group(2)
        drive_path = utils_misc.get_linux_drive_path(session, drive_id)
        did = drive_path[5:]
        test.log.info("Format %s(size=%s) with %s type.", did, stg_size, stg_fstype)
        mnts = utils_disk.configure_empty_linux_disk(
            session, did, stg_size, fstype=stg_fstype
        )
        if not mnts:
            test.fail("Failed to create %s on disk %s." % (stg_fstype, did))
    finally:
        if session:
            session.close()
        vm.destroy()
