import ast
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
    Basic migration test with diffirent cache modes and i/o over nfs
    Steps:
        1. Setup one or two local nfs servers and mount each exported dir
           to two different mountpoints, one is for source vm and the other
           one is for the target vm, e.g. fs and targetfs
        2. Run the virtiofsd daemon to share fs with different cache modes
        3. Boot the source vm with the virtiofs device in step2
        4. Mount the virtiofs targets inside the guest
        5. Create a file under each virtiofs and get the md5, run fio
        6. Run the virtiofsd daemon to share the targetfs
        7. Boot the target vm with the virtiofs device in step6
        8. Do live migration from the source vm to the target vm
        9. No error occurs, the virtiofs should be mounted automatically,
           the file md5 should keep the same, fio should still be running

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def create_service(s):
        if os_type == "windows":
            error_context.context("Create virtiofs service in guest.", test.log.info)

            driver_name = params["driver_name"]
            s = utils_test.qemu.windrv_check_running_verifier(s, vm, test, driver_name)
            viofs_svc_name = params["viofs_svc_name"]
            virtio_fs_utils.create_viofs_service(
                test, params, s, service=viofs_svc_name
            )
        return s

    def delete_service():
        if os_type == "windows":
            error_context.context("Delete virtiofs service in guest.", test.log.info)
            s = vm.wait_for_login()
            virtio_fs_utils.delete_viofs_serivce(test, params, s)
            if s:
                s.close()

    def start_service(s):
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
            output = s.cmd_output(
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
                utils_misc.make_dirs(fs_dest, s)
                error_context.context(
                    "Mount virtiofs target %s to %s inside"
                    " guest." % (fs_target, fs_dest),
                    test.log.info,
                )
                if not utils_disk.mount(fs_target, fs_dest, "virtiofs", session=s):
                    utils_misc.safe_rmdir(fs_dest, session=s)
                    test.fail(f"Failed to mount virtiofs {fs_target}")
            else:
                if params["viofs_svc_name"] == "VirtioFsSvc":
                    error_context.context(
                        "Start virtiofs service in guest.", test.log.info
                    )
                    debug_log_operation = params.get("debug_log_operation")
                    if debug_log_operation:
                        s = virtio_fs_utils.operate_debug_log(
                            test, params, s, vm, debug_log_operation
                        )
                    virtio_fs_utils.start_viofs_service(test, params, s)
                else:
                    error_context.context(
                        "Start winfsp.launcher instance in guest.", test.log.info
                    )
                    fs_volume_label = fs_params["volume_label"]
                    start_multifs_instance(fs, fs_target, fs_volume_label)

                fs_dest = "%s" % virtio_fs_utils.get_virtiofs_driver_letter(
                    test, fs_target, s
                )

            guest_mnts[fs_target] = fs_dest
        return s

    def stop_service(s):
        error_context.context("Stop virtiofs service in guest.", test.log.info)
        if os_type == "linux":
            for fs_target, fs_dest in guest_mnts.items():
                utils_disk.umount(fs_target, fs_dest, "virtiofs", session=s)
                utils_misc.safe_rmdir(fs_dest, session=s)
        else:
            if params["viofs_svc_name"] == "WinFSP.Launcher":
                for fs_target in guest_mnts.keys():
                    error_context.context(
                        "Unmount fs with WinFsp.Launcher.z", test.log.info
                    )
                    instance_stop_cmd = params["instance_stop_cmd"]
                    s.cmd(instance_stop_cmd % fs_target)
            else:
                if guest_mnts:
                    virtio_fs_utils.stop_viofs_service(test, params, s)
        if s:
            s.close()

    def start_io(s):
        def do_fio(fio, dirs):
            error_context.context("Start fio process", test.log.info)
            tmo = params.get_numeric("fio_runtime", 1800)
            f = (
                params["fio_filename"] % tuple(dirs)
                if len(dirs) > 1
                else params["fio_filename"] % dirs[0]
            )
            bg_test = utils_test.BackgroundTest(
                fio.run, (params["fio_options"] % f, tmo)
            )
            bg_test.start()

            # Wait several seconds to let fio run all its jobs
            time.sleep(5)
            out = s.cmd_output(params["cmd_chk_fio"])
            test.log.debug("Started fio process: %s", out)
            procs = re.findall(params["fio_name"], out, re.M | re.I)
            if not procs:
                test.fail("Failed to run the fio process")
            return len(procs)

        def dd_file():
            fs_dest = guest_mnts[fs_target]
            guest_file = fs_params["guest_file"] % fs_dest

            error_context.context(
                "Create the file %s get its md5" % guest_file, test.log.info
            )
            io_timeout = params.get_numeric("io_timeout", 300)
            s.cmd(params["cmd_dd"] % guest_file, io_timeout)

            cmd_md5 = params["cmd_md5"] % fs_dest
            md5 = s.cmd_output(cmd_md5, io_timeout).strip().split()[0]
            guest_files_md5[fs_target] = md5
            test.log.debug("The guest file md5: %s", md5)

        fs_list = list()
        for fs in params.objects("filesystems"):
            fs_params = params.object_params(fs)
            fs_target = fs_params["fs_target"]
            fs_list.append(guest_mnts[fs_target])
            dd_file()

        fio = generate_instance(params, vm, "fio")
        fio_proc_count = do_fio(fio, fs_list)
        return fio, fio_proc_count

    def stop_io():
        if guest_fio_object:
            error_context.context("Stop fio process", test.log.info)
            guest_fio_object.clean(force=True)

    def test_migration():
        def check_fio_running():
            error_context.context("Check fio is running after migration", test.log.info)
            fio_name = params["fio_name"]
            out = session.cmd_output(params["cmd_chk_fio"])
            test.log.debug("Status of fio process: %s", out)

            procs = re.findall(fio_name, out, re.M | re.I)
            if not procs:
                test.fail("Failed to get any running fio process")
            elif len(procs) < guest_fio_count:
                test.fail("Not all started fio processes are running")

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

        def check_file_md5():
            error_context.context("Check file md5 after migration", test.log.info)
            for fs_target, original_md5 in guest_files_md5.items():
                fs_dest = guest_mnts[fs_target]
                cmd_md5 = params["cmd_md5"] % fs_dest
                md5 = session.cmd_output(cmd_md5).strip().split()[0]
                test.log.debug("File md5 after migration: %s", md5)

                if md5 != original_md5:
                    test.fail(f"Wrong file md5 found: {md5}")

        # FIXME: Replace the vm's params to use a different shared virtio fs
        vm.params["filesystems"] = vm.params["filesystems_migration"]
        src_params = ast.literal_eval(params.get("migrate_parameters", "None"))
        tgt_params = ast.literal_eval(params.get("target_migrate_parameters", "None"))
        migrate_parameters = (src_params, tgt_params)
        vm.migrate(migrate_parameters=migrate_parameters)
        session = vm.wait_for_login()

        check_service_activated()
        check_fio_running()
        check_file_md5()

        return session

    def setup_local_nfs():
        for fs in params.objects("filesystems"):
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
            if v not in VersionInterval(version):
                test.cancel(f"The required virtiofsd version >= {version}")

    guest_mnts = dict()
    guest_files_md5 = dict()
    guest_fio_object = None
    guest_fio_count = 0
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
        guest_fio_object, guest_fio_count = start_io(session)
        session = test_migration()
    finally:
        try:
            stop_io()
            stop_service(session)
            delete_service()
        finally:
            if vm:
                vm.destroy()
            cleanup_local_nfs()
