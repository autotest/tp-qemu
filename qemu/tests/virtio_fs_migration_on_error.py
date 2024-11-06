import os
import re

from virttest import error_context, utils_disk, utils_misc, utils_test, virt_vm

from provider import virtio_fs_utils


@error_context.context_aware
def run(test, params, env):
    """
    Basic migration test with diffirent cache modes over localfs
    Steps:
        1. Create a shared directory on the host and write a file
        2. Run the virtiofsd daemon on the host with different cache modes
        3. Boot the source guest with the virtiofs device in step1
        4. Mount the virtiofs targets inside the guest
        5. Create a different directory on the host and write a file
        6. Run the virtiofsd daemon to share the directory in step5
        7. Boot the target guest with the virtiofs device in step5
        8. Do migration from the source guest to the target guest
        9. No error occurs, the virtiofs is mounted automatically and
           the file content keeps the same on the target guest

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
        fs = params.get_list("filesystems")[0]
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
            if not utils_disk.mount(fs_target, fs_dest, "virtiofs", session=session):
                utils_misc.safe_rmdir(fs_dest, session=session)
                test.fail("Failed to mount virtiofs {fs_target}.")
        else:
            error_context.context("Start virtiofs service in guest.", test.log.info)
            debug_log_operation = params.get("debug_log_operation")
            if debug_log_operation:
                session = virtio_fs_utils.operate_debug_log(
                    test, params, session, vm, debug_log_operation
                )
            virtio_fs_utils.start_viofs_service(test, params, session)

            fs_dest = "%s:" % virtio_fs_utils.get_virtiofs_driver_letter(
                test, fs_target, session
            )

        guest_mnts[fs_target] = fs_dest
        return session

    def stop_service():
        error_context.context("Stop virtiofs service in guest.", test.log.info)

        session = vm.wait_for_login()
        if os_type == "linux":
            fs_target, fs_dest = list(guest_mnts.items())[0]
            utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
            utils_misc.safe_rmdir(fs_dest, session=session)
        else:
            if guest_mnts:
                virtio_fs_utils.stop_viofs_service(test, params, session)
        session.close()

    def check_message():
        log_file = os.path.join(
            test.resultsdir, params.get("debug_log_file", "debug.log")
        )
        with open(log_file, "r") as f:
            out = f.read().strip()
            m = re.search(params["chk_msg"], out, re.M)
            if m is not None:
                test.log.debug("Expected message: %s", m.group())
                return True
        return False

    def check_service_activated():
        error_context.context(
            "Check virtiofs service activated after migration.",
            test.log.info,
        )

        session = vm.wait_for_login()
        tmo = params.get_numeric("active_timeout", 10)
        if os_type == "linux":
            fs_target, fs_dest = list(guest_mnts.items())[0]
            if not utils_misc.wait_for(
                lambda: utils_disk.is_mount(
                    fs_target, fs_dest, "virtiofs", None, True, session
                ),
                tmo,
            ):
                test.log.fail(f"Failed to mount {fs_target}")
        else:
            fs_target = list(guest_mnts.keys())[0]
            vol_lable = virtio_fs_utils.get_virtiofs_driver_letter(
                test, fs_target, session
            )
            test.log.debug("Fs target %s mounted on volume %s", fs_target, vol_lable)
        session.close()

    def check_file_content():
        error_context.context("Check file content", test.log.info)
        fs_dest = list(guest_mnts.values())[0]
        out = session.cmd_output(params["read_file_cmd"] % fs_dest).strip()
        test.log.debug("File content: %s", out)
        if out != params["test_data"]:
            test.fail(f"Wrong file content found: {out}")

    def test_migration_abort():
        check_file_content()
        try:
            vm.migrate()
        except virt_vm.VMMigrateFailedError:
            # Sometimes we got status: failed, mostly we got status: completed
            test.log.debug("Expected migration failure")

        error_context.context("Check error message after migration", test.log.info)
        tmo = params.get_numeric("chk_msg_timeout", 600)
        if not utils_misc.wait_for(check_message, tmo, step=30):
            test.fail("Failed to get the expected message")

    def test_migration_guest_error():
        vm.migrate()
        check_service_activated()

    guest_mnts = dict()
    os_type = params["os_type"]
    on_error = params["on_error"]
    test_funcs = {
        "abort": test_migration_abort,
        "guest_error": test_migration_guest_error,
    }

    vm = env.get_vm(params.get("main_vm"))
    vm.verify_alive()
    session = vm.wait_for_login()

    try:
        session = create_service(session)
        session = start_service(session)
        # FIXME: Replace the vm's params to use a different shared virtio fs
        vm.params["filesystems"] = vm.params["filesystems_migration"]
        test_funcs[on_error]()
    finally:
        if not vm.is_dead():
            stop_service()
            delete_service()
