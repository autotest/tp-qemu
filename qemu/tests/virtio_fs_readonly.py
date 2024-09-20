from virttest import error_context, utils_disk, utils_misc


@error_context.context_aware
def run(test, params, env):
    """
    Test virtio-fs with mounting by read-only options.
    Steps:
        1. Create a shared directory for testing on the host.
        2. Run the virtiofsd daemon on the host.
        3. Boot a guest on the host.
        4. Log into guest then mount the virtiofs with option "-o ro".
        5. Generate a file on the mount point in guest.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    fs_target = params.get("fs_target")
    fs_dest = params.get("fs_dest")

    vm = env.get_vm(params.get("main_vm"))
    vm.verify_alive()
    session = vm.wait_for_login()

    error_context.context("Create a destination directory inside guest.", test.log.info)
    utils_misc.make_dirs(fs_dest, session)

    error_context.context(
        "Mount the virtiofs target with read-only to "
        "the destination directory inside guest.",
        test.log.info,
    )
    if not utils_disk.mount(fs_target, fs_dest, "virtiofs", "ro", session=session):
        test.fail("Mount virtiofs target failed.")

    try:
        error_context.context(
            "Create file under the destination " "directory inside guest.",
            test.log.info,
        )
        output = session.cmd_output(params.get("cmd_create_file"))
        test.log.info(output)
        if params.get("check_str") not in output:
            test.fail("Failed to mount the virtiofs target with read-only.")
    finally:
        utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
        utils_misc.safe_rmdir(fs_dest, session=session)
