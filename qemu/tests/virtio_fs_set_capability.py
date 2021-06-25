import logging
import os
import shutil

import aexpect

from avocado.utils import process

from virttest import data_dir
from virttest import env_process
from virttest import error_context
from virttest import utils_disk
from virttest import utils_misc
from virttest import utils_test

from virttest.utils_windows import virtio_win


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
            get_product_dirname = getattr(virtio_win,
                                          "product_dirname_%s" % media_type)
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

        exe_middle_path = ("{name}\\{arch}" if media_type == "iso"
                           else "{arch}\\{name}").format(name=guest_name,
                                                         arch=guest_arch)
        exe_file_name = "virtiofs.exe"
        exe_find_cmd = 'dir /b /s %s\\%s | findstr "\\%s\\\\"'
        exe_find_cmd %= (viowin_ltr, exe_file_name, exe_middle_path)
        exe_path = session.cmd(exe_find_cmd).strip()
        logging.info("Found exe file '%s'", exe_path)
        return exe_path

    # data io config
    cmd_dd = params.get('cmd_dd')
    cmd_md5 = params.get('cmd_md5')
    io_timeout = params.get_numeric('io_timeout')

    # remove capability config
    cmd_create_fs_source = params.get('cmd_create_fs_source')
    cmd_run_virtiofsd = params.get('cmd_run_virtiofsd')
    capability = params.get('capability')
    cmd_capsh_print = params.get('cmd_capsh_print')
    cmd_capsh_drop = params.get('cmd_capsh_drop')

    # set trusted config
    cmd_yum_attr = params.get('cmd_yum_attr')
    cmd_set_trusted = params.get('cmd_set_trusted')
    cmd_get_trusted = params.get('cmd_get_trusted')
    cmd_create_file = params.get('cmd_create_file')
    cmd_set_capability = params.get('cmd_set_capability')
    cmd_get_capability = params.get('cmd_get_capability')
    cmd_echo_file = params.get('cmd_echo_file')

    # set fs daemon path
    fs_source = params.get('fs_source_dir')
    base_dir = params.get('fs_source_base_dir', data_dir.get_data_dir())

    if not os.path.isabs(fs_source):
        fs_source = os.path.join(base_dir, fs_source)
    if os.path.exists(fs_source):
        shutil.rmtree(fs_source, ignore_errors=True)
    logging.info("Create filesystem source %s.", fs_source)
    os.makedirs(fs_source)

    sock_path = os.path.join(data_dir.get_tmp_dir(),
                             '-'.join(('avocado-vt-vm1', 'viofs', 'virtiofsd.sock')))
    params['fs_source_user_sock_path'] = sock_path

    # set capability
    cmd_capsh_drop = (cmd_capsh_drop % capability)
    error_context.context("Remove capability on host.", logging.info)
    session = aexpect.ShellSession(cmd_capsh_drop, auto_close=False,
                                   output_func=utils_misc.log_line,
                                   output_params=('virtiofs_fs-virtiofs.log',),
                                   prompt=r"^\[.*\][\#\$]\s*$")
    output = session.cmd_output(cmd_capsh_print)
    logging.info("Check current capability is %s.", output)
    if capability in output:
        test.error("It's failed to check the trusted info from the host.")

    # run daemon
    session.sendline(cmd_create_fs_source)
    cmd_run_virtiofsd = cmd_run_virtiofsd % sock_path
    cmd_run_virtiofsd += ' -o source=%s' % fs_source
    cmd_run_virtiofsd += params.get('fs_binary_extra_options')
    logging.info('Running daemon command %s.', cmd_run_virtiofsd)
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
        session = utils_test.qemu.windrv_check_running_verifier(session,
                                                                vm, test,
                                                                driver_name)
        # Install winfsp tool
        error_context.context("Install winfsp for windows guest.",
                              logging.info)
        is_installed = session.cmd_status(check_installed_cmd) == 0
        if is_installed:
            logging.info("Winfsp tool is already installed.")
        else:
            install_cmd = utils_misc.set_winutils_letter(session,
                                                         params["install_cmd"])
            session.cmd(install_cmd, cmd_timeout)
            if not utils_misc.wait_for(lambda: not session.cmd_status(
                    check_installed_cmd), 60):
                test.error("Winfsp tool is not installed.")

    fs_params = params.object_params('fs')
    fs_target = fs_params.get("fs_target")
    fs_dest = fs_params.get("fs_dest")
    host_data = os.path.join(fs_source, 'fs_test')

    if not is_windows:
        error_context.context("Create a destination directory %s "
                              "inside guest." % fs_dest, logging.info)
        utils_misc.make_dirs(fs_dest, session)
        error_context.context("Mount virtiofs target %s to %s inside"
                              " guest." % (fs_target, fs_dest),
                              logging.info)
        if not utils_disk.mount(fs_target, fs_dest, 'virtiofs', session=session):
            test.fail('Mount virtiofs target failed.')
    else:
        error_context.context("Start virtiofs service in guest.", logging.info)
        viofs_sc_create_cmd = params["viofs_sc_create_cmd"]
        viofs_sc_start_cmd = params["viofs_sc_start_cmd"]
        viofs_sc_query_cmd = params["viofs_sc_query_cmd"]

        logging.info("Check if virtiofs service is registered.")
        status, output = session.cmd_status_output(viofs_sc_query_cmd)
        if "not exist as an installed service" in output:
            logging.info("Register virtiofs service in windows guest.")
            exe_path = get_viofs_exe(session)
            viofs_sc_create_cmd = viofs_sc_create_cmd % exe_path
            sc_create_s, sc_create_o = session.cmd_status_output(viofs_sc_create_cmd)
            if sc_create_s != 0:
                test.fail("Failed to register virtiofs service, output is %s" % sc_create_o)

        logging.info("Check if virtiofs service is started.")
        status, output = session.cmd_status_output(viofs_sc_query_cmd)
        if "RUNNING" not in output:
            logging.info("Start virtiofs service.")
            sc_start_s, sc_start_o = session.cmd_status_output(viofs_sc_start_cmd)
            if sc_start_s != 0:
                test.fail("Failed to start virtiofs service, output is %s" % sc_start_o)
        else:
            logging.info("Virtiofs service is running.")

        # get fs dest for vm
        virtio_fs_disk_label = fs_target
        error_context.context("Get Volume letter of virtio fs target, the disk"
                              "lable is %s." % virtio_fs_disk_label,
                              logging.info)
        vol_con = "VolumeName='%s'" % virtio_fs_disk_label
        vol_func = utils_misc.get_win_disk_vol(session, condition=vol_con)
        volume_letter = utils_misc.wait_for(lambda: vol_func, 120)
        if volume_letter is None:
            test.fail("Could not get virtio-fs mounted volume letter.")
        fs_dest = "%s:" % volume_letter

    guest_file = os.path.join(fs_dest, 'fs_test')
    logging.info("The guest file in shared dir is %s.", guest_file)

    try:
        # No extended attributes (file steams) in virtio-fs for windows
        if not is_windows:
            if cmd_set_trusted:
                error_context.context("Trusted attribute test without "
                                      "%s for linux guest" % capability, logging.info)
                host_attributes = params["host_attributes"]
                guest_trusted = params["guest_trusted"]
                file_capability = params["file_capability"]
                logging.info("Set a trusted on guest.")
                session.cmd(cmd_yum_attr)
                session.cmd(cmd_set_trusted)
                output = session.cmd_output(cmd_get_trusted)
                logging.info("Failed to check the trusted attribute from "
                             "guest, the output is %s.", output)
                if guest_trusted not in output:
                    test.fail("It's failed to check the trusted info from the guest.")

                process.run(cmd_yum_attr)
                output = str(process.run('getfattr %s' % fs_source).stdout.strip())
                logging.info("The host file trusted is %s.", output)
                if host_attributes not in output:
                    test.fail("Failed to check the trusted attribute from "
                              "host, the output is %s." % output)

                session.cmd(cmd_create_file)
                error_context.context("Privileged capabilities test without "
                                      "%s for linux guest" % capability, logging.info)
                session.cmd(cmd_set_capability)
                output = session.cmd_output(cmd_get_capability)
                logging.info("The guest file capability is %s.", output)
                if file_capability not in output:
                    test.fail("Failed to check the trusted attribute from "
                              "guest, the output is %s." % output)
                logging.info("Modify file content and check the file capability.")
                session.cmd(cmd_echo_file)
                output = session.cmd_output(cmd_get_capability)
                logging.info("The guest change file capability is %s.", output)
                if file_capability in output:
                    test.fail("Still can get capability after file content is changed.")

        if cmd_dd:
            error_context.context("Creating file under %s inside guest." %
                                  fs_dest, logging.info)
            session.cmd(cmd_dd % guest_file, io_timeout)

            if not is_windows:
                cmd_md5_vm = cmd_md5 % guest_file
            else:
                guest_file_win = guest_file.replace("/", "\\")
                cmd_md5_vm = cmd_md5 % (volume_letter, guest_file_win)
            md5_guest = session.cmd_output(cmd_md5_vm, io_timeout).strip().split()[0]

            logging.info(md5_guest)
            md5_host = process.run("md5sum %s" % host_data,
                                   io_timeout).stdout_text.strip().split()[0]
            if md5_guest != md5_host:
                test.fail('The md5 value of host is not same to guest.')

    finally:
        if not is_windows:
            utils_disk.umount(fs_target, fs_dest, 'virtiofs', session=session)
            utils_misc.safe_rmdir(fs_dest, session=session)
        session.close()
        vm.destroy()
