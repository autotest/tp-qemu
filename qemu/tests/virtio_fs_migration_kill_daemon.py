import re
import time

from avocado.utils import process
from virttest import env_process, error_context, nfs, utils_disk, utils_misc, utils_test

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
        9. Kill the source/target virtiofs daemon during the migration
        10. Check the VM and the virtiofsd mount dir status

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

    def do_fio(session):
        error_context.context("Start fio process", test.log.info)
        tmo = params.get_numeric("fio_runtime", 1800)
        fs = params["filesystems"]
        fs_params = params.object_params(fs)
        fs_target = fs_params["fs_target"]
        fs_dest = guest_mnts[fs_target]

        fio = generate_instance(params, vm, "fio")
        f = params["fio_filename"] % fs_dest
        bg_test = utils_test.BackgroundTest(fio.run, (params["fio_options"] % f, tmo))
        bg_test.start()

        # Wait several seconds to let fio run all its jobs
        time.sleep(5)
        out = session.cmd_output(params["cmd_chk_fio"])
        test.log.debug("Started fio process: %s", out)
        procs = re.findall(params["fio_name"], out, re.M | re.I)
        if not procs:
            test.fail("Failed to run the fio process")

    def test_migration_kill_daemon(session):
        def check_os_status(virtiofsd_daemon, session):
            fs = params["filesystems"]
            fs_params = params.object_params(fs)
            fs_target = fs_params["fs_target"]
            fs_dest = guest_mnts[fs_target]
            error_context.context(
                "Check the os's status after killing the virtiofsd process",
                test.log.info,
            )

            if virtiofsd_daemon == "source":
                # Check that the source VM is still running
                error_context.context(
                    "Check the source VM is still running after killing "
                    "virtiofsd process",
                    test.log.info,
                )
                if not vm.monitor.verify_status("running"):
                    test.fail(
                        "Source VM is not running after killing virtiofsd process"
                    )
                # Check another directory is still accessible
                if os_type == "windows":
                    # Use C:\Windows as a known accessible directory
                    if session.cmd_status("dir C:\\Windows", timeout=10):
                        test.fail(
                            "C:\\Windows is not accessible after killing source "
                            "virtiofsd process"
                        )
                else:
                    if session.cmd_status("ls /home", timeout=10):
                        test.fail(
                            "/home is not accessible after killing source "
                            "virtiofsd process"
                        )
                # Check the mount directory is not accessible after killing virtiofsd
                # For Windows, fs_dest is like 'Z:', for Linux it's a path
                try:
                    if os_type == "windows":
                        # Try listing the drive, expect failure or timeout
                        if not session.cmd_status(f"dir {fs_dest}\\", timeout=10):
                            test.fail(
                                "Mount dir %s is still accessible after killing source "
                                "virtiofsd process" % fs_dest
                            )
                    else:
                        if not session.cmd_status(f"ls {fs_dest}", timeout=10):
                            test.fail(
                                "Mount dir %s is still accessible after killing source "
                                "virtiofsd process" % fs_dest
                            )
                except Exception as e:
                    # If a timeout or error occurs, this is expected
                    test.log.info(
                        "Listing %s failed or timed out as expected after killing "
                        "virtiofsd: %s",
                        fs_dest,
                        e,
                    )
            elif virtiofsd_daemon == "target":
                if utils_misc.wait_for(vm.mig_succeeded, timeout=120, first=10):
                    if not vm.monitor.verify_status("postmigrate"):
                        test.fail(
                            "The VM is not paused(postmigrate) after killing the "
                            "target virtiofsd daemon"
                        )
                        error_context.context("Continue the source VM", test.log.info)
                    else:
                        vm.monitor.cmd("migrate_cancel")
                        test.log.info("The source VM is paused, resume it now")
                        try:
                            vm.resume()
                        except Exception as e:
                            test.fail(
                                "Resume the source VM failed after killing the target "
                                "virtiofsd: %s" % e
                            )
                    test.log.debug("Check the mount dir, which should be accessable")
                    if os_type == "windows":
                        session.cmd(f"dir {fs_dest}\\", timeout=10)
                    else:
                        session.cmd(f"ls {fs_dest}", timeout=10)
                else:
                    test.fail("The migration is timeout")

        def kill_virtiofsd_check(session):
            error_context.context(
                "Kill the virtiofsd process during migration", test.log.info
            )
            kill_cmd = params["kill_virtiofsd_cmd"]

            # Find the source virtiofsd process by name
            shared_dir = None
            daemon = params["daemon"]
            if daemon == "source":
                shared_dir = params.get("fs_source_dir_fs")
            elif daemon == "target":
                shared_dir = params.get("nfs_mount_dir_target")
            else:
                test.fail("Unknown daemon type: %s" % daemon)
            # Find the PID of the virtiofsd process by matching the shared directory
            cmd = (
                f"ps aux | grep -E '[v]irtiofsd.* --shared-dir {shared_dir}' "
                "| awk 'NR==1 {print $2}'"
            )
            test.log.debug("The ps command is: %s", cmd)
            pid = process.getoutput(cmd, shell=True).strip()
            if not pid:
                test.fail("Failed to find the PID of the virtiofsd process")

            test.log.debug("The virtiofsd PID: %s", pid)

            # Kill the source virtiofsd process
            process.system(kill_cmd % pid, shell=True)
            test.log.info("Killed the %s of virtiofsd process", daemon)

            # Check that the mount dir is not accessible, but others work well
            check_os_status(virtiofsd_daemon=daemon, session=session)

        def is_migration_active():
            o = vm.monitor.info("migrate")
            return o.get("status") == "active"

        # FIXME: Replace the vm's params to use a different shared virtio fs
        vm.params["filesystems"] = vm.params["filesystems_migration"]
        bg_migration = utils_test.BackgroundTest(vm.migrate, ())
        bg_migration.start()

        # Wait until the VM is in migrate status, then proceed
        if utils_misc.wait_for(is_migration_active, timeout=60, first=1, step=1):
            # Kill the virtiofsd process during migration and check
            kill_virtiofsd_check(session)
        else:
            test.fail("Migration did not become active within timeout")

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

    guest_mnts = {}
    os_type = params["os_type"]
    nfs_config = dict()
    vm = None
    session = None

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
        test_migration_kill_daemon(session)
    except Exception as e:
        test.fail("Test failed with exception: %s" % str(e))
    finally:
        if vm and vm.is_alive():
            vm.destroy(gracefully=False)
        cleanup_local_nfs()
