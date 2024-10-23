import os

from virttest import data_dir, env_process, error_context, nfs, utils_disk, utils_misc
from virttest.remote import scp_to_remote


@error_context.context_aware
def run(test, params, env):
    """
    Write to the same space test on shared directory.
    Steps:
    1. setup nfs if needed
    2. boot up guest with virtiofs device
    3. mount virtiofs on guest
    4. with mmap to write to the same space on shared dir
    5. check the size of the file

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    test_file = params.get("test_file")
    fs_dest = params.get("fs_dest")
    fs_target = params.get("fs_target")
    script_create_file = params.get("script_create_file")
    cmd_create_file = params.get("cmd_create_file")
    username = params.get("username")
    password = params.get("password")
    port = params.get("file_transfer_port")
    setup_local_nfs = params.get("setup_local_nfs", "no")

    try:
        vm = None
        if setup_local_nfs == "yes":
            nfs_local = nfs.Nfs(params)
            nfs_local.setup()
            params["start_vm"] = "yes"
            env_process.preprocess(test, params, env)
        vm = env.get_vm(params.get("main_vm"))
        vm.verify_alive()
        session = vm.wait_for_login()
        guest_addr = vm.get_address()

        error_context.context(
            "Create a destination directory %s" "inside guest." % fs_dest, test.log.info
        )
        utils_misc.make_dirs(fs_dest, session)

        error_context.context(
            "Mount virtiofs target %s to %s inside " "guest." % (fs_target, fs_dest),
            test.log.info,
        )
        if not utils_disk.mount(fs_target, fs_dest, "virtiofs", session=session):
            test.fail("Mount virtiofs target failed.")

        guest_file = os.path.join(fs_dest, test_file)
        test.log.info("The guest file in shared dir is %s", guest_file)

        error_context.context(
            "write to the same space of" " a file with mmap.", test.log.info
        )
        test.log.info("Copy the mmap script to guest.")
        host_path = os.path.join(data_dir.get_deps_dir("virtio_fs"), script_create_file)
        scp_to_remote(guest_addr, port, username, password, host_path, "/tmp")
        cmd_create_file_share = cmd_create_file % guest_file
        output = session.cmd_output(cmd_create_file_share).strip()
        if output.split()[0] != output.split()[1]:
            test.fail("The file size is increasing, the output is %s." % output)
    finally:
        if setup_local_nfs == "yes":
            if vm and vm.is_alive():
                vm.destroy()
            nfs_local.cleanup()
