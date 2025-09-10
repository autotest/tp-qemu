import aexpect
from avocado.utils import process
from virttest import error_context, utils_disk, utils_misc, utils_test

from provider import virtio_fs_utils


@error_context.context_aware
def run(test, params, env):
    """
    Test virtio-fs rlimit-nofile.
    Steps:
        1. Create a shared directory for testing on the host.
        2. Touch 1024 files in the shared directory.
        3. Start the virtiofsd daemon with rlimit-nofile and check.

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
        fs = params["filesystems"]
        fs_params = params.object_params(fs)

        fs_target = fs_params["fs_target"]
        fs_dest = fs_params["fs_dest"]

        if os_type == "linux":
            utils_misc.make_dirs(fs_dest, session)
            error_context.context(
                "Mount virtiofs target %s to %s inside guest." % (fs_target, fs_dest),
                test.log.info,
            )
            if not utils_disk.mount(fs_target, fs_dest, "virtiofs", session=session):
                utils_misc.safe_rmdir(fs_dest, session=session)
                test.fail("Failed to mount virtiofs %s." % fs_target)
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

    def stop_service(session):
        error_context.context("Stop virtiofs service in guest.", test.log.info)

        if os_type == "linux":
            for fs_target, fs_dest in guest_mnts.items():
                utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
                utils_misc.safe_rmdir(fs_dest, session=session)
        else:
            if guest_mnts:
                virtio_fs_utils.stop_viofs_service(test, params, session)
        session.close()

    rlimit_nofile = params.get("rlimit_nofile")
    cmd_run_virtiofsd = params["cmd_run_virtiofsd"]
    guest_mnts = dict()
    os_type = params["os_type"]

    if rlimit_nofile == "512":
        expected_msg = params["expected_msg"]
        error_context.context(
            "Starting virtiofsd with rlimit-nofile=%s" % rlimit_nofile, test.log.info
        )
        result = process.run(
            cmd_run_virtiofsd,
            shell=True,
            ignore_status=True,
            verbose=True,
        )
        # Prefer text-safe access for command output (stderr for failure path)
        status = result.exit_status
        err_out = result.stderr_text
        if status == 0:
            test.fail(
                "virtiofsd unexpectedly started successfully with rlimit-nofile=512"
            )
        elif expected_msg not in err_out:
            test.fail(
                "virtiofsd failed but without expected message. Output: %s" % err_out
            )
        test.log.info("virtiofsd failed as expected with the required message present")
    elif rlimit_nofile == "610":
        expected_msg = params["expected_msg"]
        error_context.context(
            "Starting virtiofsd with rlimit-nofile=%s" % rlimit_nofile, test.log.info
        )
        session = aexpect.ShellSession(
            cmd_run_virtiofsd,
            auto_close=False,
            output_func=utils_misc.log_line,
            output_params=("virtiofs_fs-virtiofs.log",),
            prompt=r"^\[.*\][\#\$]\s*$",
        )
        try:
            session.read_until_any_line_matches([expected_msg], timeout=10)
            test.log.info(
                "virtiofsd started successfully with the required message present"
            )
        except aexpect.ExpectTimeoutError as e:
            test.fail("Timeout for virtiofsd start with rlimit-nofile=610: %s" % e)
        finally:
            session.close()
    elif rlimit_nofile in (
        "1000",
        "2048",
    ):
        error_context.context(
            "Starting virtiofsd with rlimit-nofile=%s" % rlimit_nofile, test.log.info
        )
        vm = env.get_vm(params.get("main_vm"))
        vm.verify_alive()
        session = vm.wait_for_login()
        try:
            session = create_service(session)
            session = start_service(session)
            for fs_dest in guest_mnts.values():
                if rlimit_nofile == "1000":
                    # ls the dir in guest
                    out = session.cmd_output(params["list_file_cmd"] % fs_dest).strip()
                    test.log.debug("The dir output in guest: %s", out)
                    # check the qemu log whether there is the proper information
                    if params.get("ls_check_content") not in out:
                        test.fail("The list output is not proper: %s" % out)
                else:
                    cmd = params["list_file_cmd"] % fs_dest
                    status, output = session.cmd_status_output(cmd)
                    output = output.strip()
                    if status != 0:
                        test.fail("list failed: %s" % output)
        finally:
            stop_service(session)
            delete_service()
