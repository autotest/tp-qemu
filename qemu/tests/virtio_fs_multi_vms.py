import os

from virttest import error_context, utils_disk, utils_misc, utils_test
from virttest.utils_windows import virtio_win

from provider import win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    Test to virtio-fs with the multiple VMs and virtiofs daemons.
    Steps:
        1. Create shared directories on the host.
        2. Run virtiofs daemons on the host.
        3. Boot guests on the host with virtiofs options.
        4. Log into guest then mount the virtiofs targets.
        5. Generate files on the mount points inside guests.
        6. Compare the md5 among guests if multiple virtiofs
           daemons share the source.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def get_viofs_exe(session):
        """
        Get viofs.exe from virtio win iso,such as E:\viofs\2k19\amd64
        """
        test.log.info("Get virtiofs exe full path.")
        media_type = params["virtio_win_media_type"]
        try:
            get_drive_letter = getattr(virtio_win, "drive_letter_%s" % media_type)
            get_product_dirname = getattr(virtio_win, "product_dirname_%s" % media_type)
            get_arch_dirname = getattr(virtio_win, "arch_dirname_%s" % media_type)
        except AttributeError:
            test.error("Not supported virtio win media type '%s'", media_type)
        viowin_ltr = get_drive_letter(session)
        if not viowin_ltr:
            test.error("Could not find virtio-win drive in guest")
        guest_name = get_product_dirname(session)
        if not guest_name:
            test.error("Could not get product dirname of the vm")
        guest_arch = get_arch_dirname(session)
        if not guest_arch:
            test.error("Could not get architecture dirname of the vm")

        exe_middle_path = (
            "{name}\\{arch}" if media_type == "iso" else "{arch}\\{name}"
        ).format(name=guest_name, arch=guest_arch)
        exe_file_name = "virtiofs.exe"
        exe_find_cmd = 'dir /b /s %s\\%s | findstr "\\%s\\\\"'
        exe_find_cmd %= (viowin_ltr, exe_file_name, exe_middle_path)
        exe_path = session.cmd(exe_find_cmd).strip()
        test.log.info("Found exe file '%s'", exe_path)
        return exe_path

    cmd_dd = params.get("cmd_dd")
    cmd_md5 = params.get("cmd_md5")
    io_timeout = params.get_numeric("io_timeout")
    shared_fs_source_dir = params.get("shared_fs_source_dir")
    os_type = params.get("os_type")

    # cfg for windows vm
    cmd_timeout = params.get_numeric("cmd_timeout", 120)
    driver_name = params.get("driver_name")
    wfsp_install_cmd = params.get("wfsp_install_cmd")
    check_installed_cmd = params.get("check_installed_cmd")

    sessions = []
    vms = env.get_all_vms()
    for vm in vms:
        vm.verify_alive()
        sessions.append(vm.wait_for_login())

    mapping = {}
    for vm, vm_obj, session in zip(params.objects("vms"), vms, sessions):
        vm_params = params.object_params(vm)
        mapping[vm] = {"session": session, "vm_obj": vm_obj, "filesystems": []}

        # check driver verifier in windows vm
        # install winfsp tool and start virtiofs exe in windows vm
        if os_type == "windows":
            # Check whether windows driver is running,and enable driver verifier
            session = utils_test.qemu.windrv_check_running_verifier(
                session, vm_obj, test, driver_name
            )
            error_context.context(
                "%s: Install winfsp for windows guest." % vm, test.log.info
            )
            installed = session.cmd_status(check_installed_cmd) == 0
            if installed:
                test.log.info("%s: Winfsp tool is already installed.", vm)
            else:
                install_cmd = utils_misc.set_winutils_letter(session, wfsp_install_cmd)
                session.cmd(install_cmd, cmd_timeout)
                if not utils_misc.wait_for(
                    lambda: not session.cmd_status(check_installed_cmd), 60
                ):
                    test.error("%s: Winfsp tool is not installed." % vm)

            error_context.context(
                "%s: Start virtiofs service in guest." % vm, test.log.info
            )
            viofs_sc_create_cmd = params["viofs_sc_create_cmd"]
            viofs_sc_start_cmd = params["viofs_sc_start_cmd"]
            viofs_sc_query_cmd = params["viofs_sc_query_cmd"]

            test.log.info("Check if virtiofs service is registered.")
            status, output = session.cmd_status_output(viofs_sc_query_cmd)
            if "not exist as an installed service" in output:
                test.log.info("Register virtiofs service in windows guest.")
                exe_path = get_viofs_exe(session)
                # copy virtiofs.exe to c: in case the virtio-win cdrom volume name
                # is changed in other cases of a loop.
                session.cmd(params.get("viofs_exe_copy_cmd") % exe_path)
                sc_create_s, sc_create_o = session.cmd_status_output(
                    viofs_sc_create_cmd
                )
                if sc_create_s != 0:
                    test.fail(
                        "Failed to register virtiofs service, output is %s"
                        % sc_create_o
                    )

            test.log.info("Check if virtiofs service is started.")
            status, output = session.cmd_status_output(viofs_sc_query_cmd)
            if "RUNNING" not in output:
                test.log.info("Start virtiofs service.")
                sc_start_s, sc_start_o = session.cmd_status_output(viofs_sc_start_cmd)
                if sc_start_s != 0:
                    test.fail(
                        "Failed to start virtiofs service, output is %s" % sc_start_o
                    )
            else:
                test.log.info("Virtiofs service is running.")
            # enable debug log.
            viofs_debug_enable_cmd = params.get("viofs_debug_enable_cmd")
            viofs_log_enable_cmd = params.get("viofs_log_enable_cmd")
            if viofs_debug_enable_cmd and viofs_log_enable_cmd:
                error_context.context(
                    "Check if virtiofs debug log is enabled in guest.", test.log.info
                )
                cmd = params.get("viofs_reg_query_cmd")
                ret = session.cmd_output(cmd)
                if "debugflags" not in ret.lower() or "debuglogfile" not in ret.lower():
                    error_context.context(
                        "Configure virtiofs debug log.", test.log.info
                    )
                    for reg_cmd in (viofs_debug_enable_cmd, viofs_log_enable_cmd):
                        error_context.context("Set %s " % reg_cmd, test.log.info)
                        s, o = session.cmd_status_output(reg_cmd)
                        if s:
                            test.fail("Fail command: %s. Output: %s" % (reg_cmd, o))
                    error_context.context("Reboot guest.", test.log.info)
                    session = vm_obj.reboot()
                    # session is updated in reboot steps, so it should be updated.
                    mapping[vm]["session"] = session
                else:
                    test.log.info("Virtiofs debug log is enabled.")

        # get fs dest for vm
        for fs in vm_params.objects("filesystems"):
            fs_params = vm_params.object_params(fs)
            fs_target = fs_params.get("fs_target")
            fs_dest = fs_params.get("fs_dest")

            if os_type == "linux":
                error_context.context(
                    "%s: Create a destination directory %s inside guest."
                    % (vm, fs_dest),
                    test.log.info,
                )
                utils_misc.make_dirs(fs_dest, session)

                error_context.context(
                    "%s: Mount the virtiofs target %s to %s inside guest."
                    % (vm, fs_target, fs_dest),
                    test.log.info,
                )
                if not utils_disk.mount(
                    fs_target, fs_dest, "virtiofs", session=session
                ):
                    test.fail("Mount virtiofs target failed.")
            else:
                virtio_fs_disk_label = fs_target
                error_context.context(
                    "%s: Get Volume letter of virtio fs"
                    " target, the disk lable is %s." % (vm, virtio_fs_disk_label),
                    test.log.info,
                )
                vol_con = "VolumeName='%s'" % virtio_fs_disk_label
                vol_func = utils_misc.get_win_disk_vol(session, condition=vol_con)
                volume_letter = utils_misc.wait_for(lambda: vol_func, cmd_timeout)
                if volume_letter is None:
                    test.fail(
                        "Could not get virtio-fs mounted volume"
                        " letter for %s." % fs_target
                    )
                fs_dest = "%s:" % volume_letter

            guest_file = os.path.join(fs_dest, "fs_test")
            test.log.info("%s: The guest file in shared dir is %s", vm, guest_file)
            mapping[vm]["filesystems"].append(
                {"fs_target": fs_target, "fs_dest": fs_dest, "guest_file": guest_file}
            )

            if cmd_dd:
                test.log.info("%s: Creating file under %s inside guest.", vm, fs_dest)
                session.cmd(cmd_dd % guest_file, io_timeout)

            if shared_fs_source_dir:
                continue

            if os_type == "linux":
                error_context.context(
                    "%s: Umount the viriofs target %s." % (vm, fs_target), test.log.info
                )
                utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
    if shared_fs_source_dir:
        error_context.context("Compare the md5 among VMs.", test.log.info)
        md5_set = set()
        for vm, info in mapping.items():
            session = info["session"]
            for fs in info["filesystems"]:
                shared_data = fs["guest_file"]
                error_context.context(
                    "%s: Get the md5 of %s." % (vm, shared_data), test.log.info
                )
                if os_type == "linux":
                    cmd_md5_vm = cmd_md5 % shared_data
                else:
                    guest_file_win = shared_data.replace("/", "\\")
                    cmd_md5_vm = cmd_md5 % (volume_letter, guest_file_win)

                md5_guest = session.cmd(cmd_md5_vm, io_timeout).strip().split()[0]
                test.log.info(md5_guest)
                md5_set.add(md5_guest)

                if os_type == "linux":
                    error_context.context(
                        "%s: Umount the viriofs target %s." % (vm, fs["fs_target"]),
                        test.log.info,
                    )
                    utils_disk.umount(
                        fs["fs_target"], fs["fs_dest"], "virtiofs", session=session
                    )
        if len(md5_set) != 1:
            test.fail("The md5 values are different among VMs.")

    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if os_type == "windows":
        for vm, info in mapping.items():
            vm_obj = info["vm_obj"]
            vm_params = params.object_params(vm)
            win_driver_utils.memory_leak_check(vm_obj, test, vm_params)
