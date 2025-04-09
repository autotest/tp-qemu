from avocado.utils import process
from virttest import error_context, utils_disk, utils_misc, utils_test
from virttest.utils_version import VersionInterval

from provider import virtio_fs_utils


@error_context.context_aware
def run(test, params, env):
    """
    Test virtio-fs daemon exported with --read-only option.
    Steps:
        1. Create a shared directory and a file for testing on the host.
        2. Run the virtiofsd daemon with --readonly on the host.
        3. Boot a guest on the host.
        4. Log into guest then mount the virtiofs.
        5. Test the mount dir is readonly.

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

    def test_readonly():
        def check_file_content():
            error_context.context(
                "Check file content after mounting.",
                test.log.info,
            )

            for fs_dest in guest_mnts.values():
                out = session.cmd_output(params["read_file_cmd"] % fs_dest).strip()
                test.log.debug("File content: %s", out)
                if out != params["test_data"]:
                    test.fail(f"Wrong file content found: {out}")

        def write_file():
            error_context.context(
                "Write the file after mounting.",
                test.log.info,
            )

            for fs_dest in guest_mnts.values():
                output = session.cmd_output(params.get("write_file_cmd") % fs_dest)
                test.log.info(output)
                if params.get("check_str") not in output:
                    test.fail("The mounted dir is not read-only.")

        check_file_content()
        write_file()

    def check_virtiofsd_version():
        version = params.get("required_virtiofsd_version")
        if version:
            v = process.getoutput(params["virtiofsd_version_cmd"], shell=True).strip()
            test.log.debug("The virtiofsd version: %s", v)
            if v not in VersionInterval(version):
                test.cancel(f"The required virtiofsd version >= {version}")

    guest_mnts = dict()
    os_type = params["os_type"]

    check_virtiofsd_version()
    vm = env.get_vm(params.get("main_vm"))
    vm.verify_alive()
    session = vm.wait_for_login()

    try:
        session = create_service(session)
        session = start_service(session)
        test_readonly()
    finally:
        stop_service(session)
        delete_service()
