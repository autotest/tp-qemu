import re

from virttest import env_process, error_context, nfs, utils_disk, utils_misc, utils_test

from provider import virtio_fs_utils


@error_context.context_aware
def run(test, params, env):
    """
    Migration test over nfs with handler verify and path confirm
    Steps:
        1. Create a nfs share dir and write a file
        2. Setup a local nfs server and mount fs to dirs fs and targetfs
        3. Run the virtiofsd daemon to share fs
        4. Boot the source guest with the virtiofs device in step3
        5. Mount the virtiofs targets inside the guest
        6. Check the file content and open the file by tail
        7. Run the virtiofsd daemon to share targetfs
        8. Boot the target guest with the virtiofs device in step7
        9. Do migration from the source guest to the target guest
       10. No error occurs, the virtiofs is mounted automatically and
           the file cotent keeps the same, tail is still running

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def create_service(session):
        if os_type == "windows":
            error_context.context("Create virtiofs service in guest.", test.log.info)

            driver_name = params["driver_name"]
            session = utils_test.qemu.windrv_check_running_verifier(
                session, vm, test, driver_name
            )
            viofs_svc_name = params["viofs_svc_name"]
            virtio_fs_utils.create_viofs_service(
                test, params, session, service=viofs_svc_name
            )
        return session

    def delete_service():
        if os_type == "windows":
            error_context.context("Delete virtiofs service in guest.", test.log.info)
            session = vm.wait_for_login()
            virtio_fs_utils.delete_viofs_serivce(test, params, session)
            session.close()

    def start_service(session):
        def start_multifs_instance(fs_tag, fs_target, fs_volume_label):
            """
            Only for windows and only for multiple shared directory.
            """
            error_context.context(
                "MultiFS-%s: Start virtiofs instance with"
                " tag %s to %s." % (fs_tag, fs_target, fs_volume_label),
                test.log.info,
            )
            instance_start_cmd = params["instance_start_cmd"]
            output = session.cmd_output(
                instance_start_cmd % (fs_target, fs_target, fs_volume_label)
            )
            if re.search("KO.*error", output, re.I):
                test.fail(
                    "MultiFS-%s: Start virtiofs instance failed, "
                    "output is %s." % (fs_tag, output)
                )

        for fs in params.objects("filesystems"):
            fs_params = params.object_params(fs)

            fs_target = fs_params["fs_target"]
            fs_dest = fs_params["fs_dest"]

            if os_type == "linux":
                utils_misc.make_dirs(fs_dest, session)
                error_context.context(
                    "Mount virtiofs target %s to %s inside"
                    " guest." % (fs_target, fs_dest),
                    test.log.info,
                )
                if not utils_disk.mount(
                    fs_target, fs_dest, "virtiofs", session=session
                ):
                    utils_misc.safe_rmdir(fs_dest, session=session)
                    test.fail(f"Failed to mount virtiofs {fs_target}")
            else:
                if params["viofs_svc_name"] == "VirtioFsSvc":
                    error_context.context(
                        "Start virtiofs service in guest.", test.log.info
                    )
                    debug_log_operation = params.get("debug_log_operation")
                    if debug_log_operation:
                        session = virtio_fs_utils.operate_debug_log(
                            test, params, session, vm, debug_log_operation
                        )
                    virtio_fs_utils.start_viofs_service(test, params, session)
                else:
                    error_context.context(
                        "Start winfsp.launcher instance in guest.", test.log.info
                    )
                    fs_volume_label = fs_params["volume_label"]
                    start_multifs_instance(fs, fs_target, fs_volume_label)

                fs_dest = "%s:" % virtio_fs_utils.get_virtiofs_driver_letter(
                    test, fs_target, session
                )

            guest_mnts[fs_target] = fs_dest
        return session

    def stop_service(session):
        error_context.context("Stop virtiofs service in guest.", test.log.info)
        if os_type == "linux":
            for fs_target, fs_dest in guest_mnts.items():
                utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
                utils_misc.safe_rmdir(fs_dest, session=session)
        else:
            if params["viofs_svc_name"] == "WinFSP.Launcher":
                for fs_target in guest_mnts.keys():
                    error_context.context(
                        "Unmount fs with WinFsp.Launcher.z", test.log.info
                    )
                    instance_stop_cmd = params["instance_stop_cmd"]
                    session.cmd(instance_stop_cmd % fs_target)
            else:
                if guest_mnts:
                    virtio_fs_utils.stop_viofs_service(test, params, session)
        session.close()

    def open_file(session):
        def do_tail():
            fs_dest = guest_mnts[fs_target]
            error_context.context("Open file on %s." % fs_dest, test.log.info)

            tmo = params.get_numeric("tail_runtime", 1800)
            bg_test = utils_test.BackgroundTest(
                session.cmd_output, (params["cmd_tail_file"] % fs_dest, tmo)
            )
            bg_test.start()

        for fs in params.objects("filesystems"):
            fs_params = params.object_params(fs)
            fs_target = fs_params["fs_target"]
            do_tail()

    def close_file(session):
        error_context.context("Close file", test.log.info)
        session.cmd_output(params["cmd_kill_tail"])

    def test_migration():
        def check_file_content():
            error_context.context(
                "Check file content",
                test.log.info,
            )
            s = vm.wait_for_login()
            for fs_dest in guest_mnts.values():
                out = s.cmd_output(params["read_file_cmd"] % fs_dest).strip()
                test.log.debug("File content: %s", out)
                if out != params["test_data"]:
                    test.fail(f"Wrong file content found: {out}")
            s.close()

        def check_tail_running():
            error_context.context(
                "Check tail is running after migration", test.log.info
            )
            tail_name = params["tail_name"]
            out = session.cmd_output(params["cmd_chk_tail"])
            test.log.debug("Status of tail process: %s", out)

            procs = re.findall(tail_name, out, re.M | re.I)
            if not procs:
                test.fail("Failed to get any running tail process")
            elif len(procs) != len(params.get_list("filesystems")):
                test.fail("Failed to get all running tail processes")

        def check_service_activated():
            error_context.context(
                "Check virtiofs service activated after migration",
                test.log.info,
            )
            tmo = params.get_numeric("active_timeout", 10)
            if os_type == "linux":
                for fs_target, fs_dest in guest_mnts.items():
                    if not utils_misc.wait_for(
                        lambda: utils_disk.is_mount(
                            fs_target, fs_dest, "virtiofs", None, True, session
                        ),
                        tmo,
                    ):
                        test.fail(f"Failed to mount {fs_target}")
            else:
                for fs_target in guest_mnts.keys():
                    vol_lable = virtio_fs_utils.get_virtiofs_driver_letter(
                        test, fs_target, session
                    )
                    test.log.debug(
                        "Fs target %s mounted on volume %s", fs_target, vol_lable
                    )

        check_file_content()

        # FIXME: Replace the vm's params to use a different shared virtio fs
        vm.params["filesystems"] = vm.params["filesystems_migration"]
        vm.migrate()
        session = vm.wait_for_login()

        check_service_activated()
        check_tail_running()
        check_file_content()

        return session

    def setup_local_nfs():
        error_context.context("Setup nfs server, mount it to two dirs", test.log.info)

        # Setup the local nfs server and mount it to nfs_mount_dir
        nfs_obj = nfs.Nfs(params)
        nfs_obj.setup()

        # Mount the local nfs server to nfs_mount_dir_targetfs
        target_params = params.copy()
        target_params["nfs_mount_dir"] = params["nfs_mount_dir_targetfs"]
        target_params["setup_local_nfs"] = "no"
        nfs_target = nfs.Nfs(target_params)
        nfs_target.mount()

        return nfs_obj, nfs_target

    def cleanup_local_nfs():
        error_context.context("Umount all and stop nfs server", test.log.info)
        if target_nfs:
            target_nfs.umount()
        if local_nfs:
            local_nfs.cleanup()

    guest_mnts = dict()
    os_type = params["os_type"]
    local_nfs = None
    target_nfs = None
    vm = None
    session = None

    try:
        local_nfs, target_nfs = setup_local_nfs()
        env_process.process(
            test, params, env, env_process.preprocess_image, env_process.preprocess_vm
        )
        vm = env.get_vm(params.get("main_vm"))
        vm.verify_alive()
        session = vm.wait_for_login()
        session = create_service(session)
        session = start_service(session)
        open_file(session)
        session = test_migration()
    finally:
        try:
            close_file(session)
            stop_service(session)
            delete_service()
        finally:
            if vm:
                vm.destroy()
            cleanup_local_nfs()
