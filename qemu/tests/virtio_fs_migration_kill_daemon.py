import ast
import os
import re
import time

from avocado.utils import process
from virttest import env_process, error_context, nfs, utils_disk, utils_misc, utils_test
from virttest.utils_version import VersionInterval

from provider import virtio_fs_utils
from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Basic migration test with different cache modes and i/o over nfs
    Steps:
        1. Setup one local nfs server and exported dir
           to two different mountpoints, one is for source vm and the other
           one is for the target vm, e.g. fs and targetfs
        2. Run the virtiofsd daemon to share fs
        3. Boot the source vm with the virtiofs device in step2
        4. Mount the virtiofs targets inside the guest
        5. Create a file under each virtiofs and get the md5, run fio
        6. Run the virtiofsd daemon to share the targetfs
        7. Boot the target vm with the virtiofs device in step6
        8. Do live migration from the source vm to the target vm
        9. Kill the source virtiofs daemon during the migration
        10. Check the VM is still running but the virtiofsd mount dir is not working

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
            s = vm.wait_for_login()
            virtio_fs_utils.delete_viofs_service(test, params, s)
            if s:
                s.close()

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
                test.fail(f"Failed to mount virtiofs {fs_target}.")
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

    def do_fio(session):
        error_context.context("Run fio in guest.", test.log.info)
        fs = params["filesystems"]
        fs_params = params.object_params(fs)
        fs_target = fs_params["fs_target"]
        dirs = [guest_mnts.get(fs_target)]
        if not dirs[0]:
            test.fail(f"Failed to retrieve mount directory for {fs_target}")

        fio = generate_instance(params, vm, "fio")
        error_context.context("Start fio process", test.log.info)
        tmo = params.get_numeric("fio_runtime", 1800)
        f = (
            params["fio_filename"] % tuple(dirs)
            if len(dirs) > 1
            else params["fio_filename"] % dirs[0]
        )
        bg_test = utils_test.BackgroundTest(fio.run, (params["fio_options"] % f, tmo))
        bg_test.start()

        # Wait several seconds to let fio run all its jobs
        time.sleep(5)
        out = session.cmd_output(params["cmd_chk_fio"])
        test.log.debug("Started fio process: %s", out)
        procs = re.findall(params["fio_name"], out, re.M | re.I)
        if not procs:
            test.fail("Failed to run the fio process")

    def test_migration():
        def check_os_dir_status():
            fs = params["filesystems"]
            fs_params = params.object_params(fs)
            fs_dest = fs_params["fs_dest"]
            error_context.context(
                "Check the mount dir status after killing the virtiofsd process",
                test.log.info,
            )

            if os.access(fs_dest, os.R_OK):
                test.fail(
                    "Mount dir %s is accessible after killing virtiofsd process"
                    % fs_dest
                )
            if not os.access("/home", os.R_OK):
                test.fail("/home is not accessible after killing virtiofsd process")

        def kill_source_virtiofsd():
            error_context.context(
                "Kill the source virtiofsd process during migration", test.log.info
            )
            fs_source_dir_fs = params.get("fs_source_dir_fs")
            kill_cmd = params["kill_virtiofsd_cmd"]

            # Find the source virtiofsd process by name
            cmd = (
                f"ps aux | grep -E '[v]irtiofsd.* --shared-dir {fs_source_dir_fs}' "
                "| awk 'NR==1 {print $2}'"
            )
            pid = process.getoutput(cmd, shell=True).strip()
            if not pid:
                test.fail("Failed to find the PID of the source virtiofsd process")

            test.log.debug("Source virtiofsd PID: %s", pid)

            # Kill the source virtiofsd process
            process.system(kill_cmd % pid, shell=True)
            test.log.info("Killed the source of virtiofsd process")

            # Check that the source VM is still running
            error_context.context(
                "Check the source VM is still running after killing virtiofsd process",
                test.log.info,
            )
            if not vm.is_alive():
                test.fail("Source VM is not running after killing virtiofsd process")

            # Check that the mount dir is not accessible, but others work wel
            check_os_dir_status()

        # FIXME: Replace the vm's params to use a different shared virtio fs
        vm.params["filesystems"] = vm.params["filesystems_migration"]
        src_params = ast.literal_eval(params.get("migrate_parameters", "None"))
        tgt_params = ast.literal_eval(params.get("target_migrate_parameters", "None"))
        migrate_parameters = (src_params, tgt_params)
        bg_migration = utils_test.BackgroundTest(vm.migrate, (migrate_parameters,))
        bg_migration.start()

        # Wait for a short period to ensure migration has started
        time.sleep(params.get_numeric("migration_start_delay", 5))

        # Kill the source virtiofsd process during migration and check
        kill_source_virtiofsd()

        return session

    def setup_local_nfs():
        fs = params["filesystems"]  # Assuming only one filesystem is used
        fs_params = params.object_params(fs)
        nfs_config[fs] = dict()

        error_context.context(
            "Setup the nfs server, mount it to two dirs", test.log.info
        )

        # Setup the local nfs server and mount it to nfs_mount_dir
        nfs_obj = nfs.Nfs(fs_params)
        nfs_obj.setup()
        nfs_config[fs]["server"] = nfs_obj

        # Mount the local nfs server to nfs_mount_dir_target
        target_params = fs_params.copy()
        target_params["nfs_mount_dir"] = fs_params["nfs_mount_dir_target"]
        target_params["setup_local_nfs"] = "no"
        nfs_target = nfs.Nfs(target_params)
        test.log.debug("Mount %s to %s", nfs_target.mount_src, nfs_target.mount_dir)
        nfs_target.mount()
        nfs_config[fs]["target"] = nfs_target

    def cleanup_local_nfs():
        error_context.context("Umount all and stop nfs server", test.log.info)
        for obj in nfs_config.values():
            if "target" in obj:
                obj["target"].umount()
            if "server" in obj:
                obj["server"].cleanup()

    def check_vertiofsd_version():
        version = params.get("required_virtiofsd_version")
        if version:
            v = process.getoutput(params["virtiofsd_version_cmd"], shell=True).strip()
            test.log.debug("The virtiofsd version: %s", v)
            try:
                if v not in VersionInterval(version):
                    test.cancel(f"The required virtiofsd version >= {version}")
            except ValueError as e:
                test.fail(f"Invalid version string format: {v}. Error: {e}")

    guest_mnts = dict()
    os_type = params["os_type"]
    nfs_config = dict()
    vm = None
    session = None

    check_vertiofsd_version()
    try:
        setup_local_nfs()
        env_process.process(
            test, params, env, env_process.preprocess_image, env_process.preprocess_vm
        )
        vm = env.get_vm(params.get("main_vm"))
        vm.verify_alive()
        session = vm.wait_for_login()
        session = create_service(session)
        session = start_service(session)
        do_fio(session)
        test_migration()
    except Exception as e:
        stop_service(session)
        delete_service()
        test.fail("Test failed with exception: %s" % str(e))
    finally:
        if vm:
            vm.destroy()
        cleanup_local_nfs()
