import os
import shutil

import aexpect
from avocado.utils import process
from virttest import (
    data_dir,
    env_process,
    error_context,
    utils_disk,
    utils_misc,
    utils_test,
)
from virttest.utils_windows import virtio_win

from provider import virtio_fs_utils, win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    Test virtio-fs by sharing the data between host and guest.
    Steps:
        1. Create shared directories on the host.
        2. Set capability on the host.
        3. Run virtiofsd daemons on capability shell env.
        4. Boot a guest on the host with virtiofs options.
        5. Log into guest then mount the virtiofs targets.
        6. Generate files or run stress on the mount points inside guest.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def get_viofs_exe(session):
        """
        Get viofs.exe from virtio win iso,such as E:\viofs\2k19\amd64
        """
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

    # data io config
    cmd_dd = params.get("cmd_dd")
    cmd_md5 = params.get("cmd_md5")
    io_timeout = params.get_numeric("io_timeout")

    # remove capability config
    cmd_create_fs_source = params.get("cmd_create_fs_source")
    cmd_run_virtiofsd = params.get("cmd_run_virtiofsd")
    capability = params.get("capability")
    cmd_capsh_print = params.get("cmd_capsh_print")
    cmd_capsh_drop = params.get("cmd_capsh_drop")

    # set trusted config
    cmd_yum_attr = params.get("cmd_yum_attr")
    cmd_set_trusted = params.get("cmd_set_trusted")
    cmd_get_trusted = params.get("cmd_get_trusted")
    cmd_create_file = params.get("cmd_create_file")
    cmd_set_capability = params.get("cmd_set_capability")
    cmd_get_capability = params.get("cmd_get_capability")
    cmd_echo_file = params.get("cmd_echo_file")

    # set fs daemon path
    fs_source = params.get("fs_source_dir")
    base_dir = params.get("fs_source_base_dir", data_dir.get_data_dir())

    if not os.path.isabs(fs_source):
        fs_source = os.path.join(base_dir, fs_source)
    if os.path.exists(fs_source):
        shutil.rmtree(fs_source, ignore_errors=True)
    test.log.info("Create filesystem source %s.", fs_source)
    os.makedirs(fs_source)

    sock_path = os.path.join(
        data_dir.get_tmp_dir(), "-".join(("avocado-vt-vm1", "viofs", "virtiofsd.sock"))
    )
    params["fs_source_user_sock_path"] = sock_path

    # set capability
    cmd_capsh_drop = cmd_capsh_drop % capability
    error_context.context("Remove capability on host.", test.log.info)
    session = aexpect.ShellSession(
        cmd_capsh_drop,
        auto_close=False,
        output_func=utils_misc.log_line,
        output_params=("virtiofs_fs-virtiofs.log",),
        prompt=r"^\[.*\][\#\$]\s*$",
    )
    output = session.cmd_output(cmd_capsh_print)
    test.log.info("Check current capability is %s.", output)
    if capability in output:
        test.error("It's failed to check the trusted info from the host.")

    # run daemon
    session.sendline(cmd_create_fs_source)
    cmd_run_virtiofsd = cmd_run_virtiofsd % sock_path
    cmd_run_virtiofsd += " -o source=%s" % fs_source
    cmd_run_virtiofsd += params.get("fs_binary_extra_options")
    test.log.info("Running daemon command %s.", cmd_run_virtiofsd)
    session.sendline(cmd_run_virtiofsd)

    params["start_vm"] = "yes"
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params.get("main_vm"))
    vm.verify_alive()
    is_windows = params.get("os_type") == "windows"
    session = vm.wait_for_login()

    if is_windows:
        cmd_timeout = params.get_numeric("cmd_timeout", 120)
        driver_name = params["driver_name"]
        install_path = params["install_path"]
        check_installed_cmd = params["check_installed_cmd"] % install_path

        # Check whether windows driver is running,and enable driver verifier
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name
        )
        # Install winfsp tool
        error_context.context("Install winfsp for windows guest.", test.log.info)
        is_installed = session.cmd_status(check_installed_cmd) == 0
        if is_installed:
            test.log.info("Winfsp tool is already installed.")
        else:
            install_cmd = utils_misc.set_winutils_letter(session, params["install_cmd"])
            session.cmd(install_cmd, cmd_timeout)
            if not utils_misc.wait_for(
                lambda: not session.cmd_status(check_installed_cmd), 60
            ):
                test.error("Winfsp tool is not installed.")

    fs_params = params.object_params("fs")
    fs_target = fs_params.get("fs_target")
    fs_dest = fs_params.get("fs_dest")
    host_data = os.path.join(fs_source, "fs_test")
    try:
        if not is_windows:
            error_context.context(
                "Create a destination directory %s " "inside guest." % fs_dest,
                test.log.info,
            )
            utils_misc.make_dirs(fs_dest, session)
            error_context.context(
                "Mount virtiofs target %s to %s inside"
                " guest." % (fs_target, fs_dest),
                test.log.info,
            )
            if not utils_disk.mount(fs_target, fs_dest, "virtiofs", session=session):
                test.fail("Mount virtiofs target failed.")
        else:
            error_context.context("Start virtiofs service in guest.", test.log.info)
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
                    session = vm.reboot()
                else:
                    test.log.info("Virtiofs debug log is enabled.")

            # get fs dest for vm
            virtio_fs_disk_label = fs_target
            error_context.context(
                "Get Volume letter of virtio fs target, the disk"
                "lable is %s." % virtio_fs_disk_label,
                test.log.info,
            )
            vol_con = "VolumeName='%s'" % virtio_fs_disk_label
            vol_func = utils_misc.get_win_disk_vol(session, condition=vol_con)
            volume_letter = utils_misc.wait_for(lambda: vol_func, 120)
            if volume_letter is None:
                test.fail("Could not get virtio-fs mounted volume letter.")
            fs_dest = "%s:" % volume_letter

        guest_file = os.path.join(fs_dest, "fs_test")
        test.log.info("The guest file in shared dir is %s.", guest_file)

        try:
            # No extended attributes (file steams) in virtio-fs for windows
            if not is_windows:
                if cmd_set_trusted:
                    error_context.context(
                        "Trusted attribute test without "
                        "%s for linux guest" % capability,
                        test.log.info,
                    )
                    host_attributes = params["host_attributes"]
                    guest_trusted = params["guest_trusted"]
                    file_capability = params["file_capability"]
                    test.log.info("Set a trusted on guest.")
                    session.cmd(cmd_yum_attr)
                    session.cmd(cmd_set_trusted)
                    output = session.cmd_output(cmd_get_trusted)
                    test.log.info(
                        "Failed to check the trusted attribute from "
                        "guest, the output is %s.",
                        output,
                    )
                    if guest_trusted not in output:
                        test.fail(
                            "It's failed to check the trusted info from the guest."
                        )

                    process.run(cmd_yum_attr)
                    output = str(process.run("getfattr %s" % fs_source).stdout.strip())
                    test.log.info("The host file trusted is %s.", output)
                    if host_attributes not in output:
                        test.fail(
                            "Failed to check the trusted attribute from "
                            "host, the output is %s." % output
                        )

                    session.cmd(cmd_create_file)
                    error_context.context(
                        "Privileged capabilities test without "
                        "%s for linux guest" % capability,
                        test.log.info,
                    )
                    session.cmd(cmd_set_capability)
                    output = session.cmd_output(cmd_get_capability)
                    test.log.info("The guest file capability is %s.", output)
                    if file_capability not in output:
                        test.fail(
                            "Failed to check the trusted attribute from "
                            "guest, the output is %s." % output
                        )
                    test.log.info("Modify file content and check the file capability.")
                    session.cmd(cmd_echo_file)
                    output = session.cmd_output(cmd_get_capability)
                    test.log.info("The guest change file capability is %s.", output)
                    if file_capability in output:
                        test.fail(
                            "Still can get capability after file content is changed."
                        )

            if cmd_dd:
                error_context.context(
                    "Creating file under %s inside guest." % fs_dest, test.log.info
                )
                session.cmd(cmd_dd % guest_file, io_timeout)

                if not is_windows:
                    cmd_md5_vm = cmd_md5 % guest_file
                else:
                    guest_file_win = guest_file.replace("/", "\\")
                    cmd_md5_vm = cmd_md5 % (volume_letter, guest_file_win)
                md5_guest = (
                    session.cmd_output(cmd_md5_vm, io_timeout).strip().split()[0]
                )

                test.log.info(md5_guest)
                md5_host = (
                    process.run("md5sum %s" % host_data, io_timeout)
                    .stdout_text.strip()
                    .split()[0]
                )
                if md5_guest != md5_host:
                    test.fail("The md5 value of host is not same to guest.")
            # for windows guest, disable/uninstall driver to get memory leak based on
            # driver verifier is enabled
            if is_windows:
                win_driver_utils.memory_leak_check(vm, test, params)
        finally:
            if not is_windows:
                utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
                utils_misc.safe_rmdir(fs_dest, session=session)
    finally:
        if is_windows:
            virtio_fs_utils.delete_viofs_serivce(test, params, session)
