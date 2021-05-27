import logging
import os

import aexpect

from avocado.utils import process

from virttest import data_dir
from virttest import env_process
from virttest import error_context
from virttest import nfs
from virttest import utils_disk
from virttest import utils_misc
from virttest import utils_test
from virttest.remote import scp_to_remote
from virttest.utils_windows import virtio_win
from virttest.qemu_devices import qdevices

from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Test virtio-fs by sharing the data between host and guest.
    Steps:
        1. Create shared directories on the host.
        2. Run virtiofsd daemons on the host.
        3. Boot a guest on the host with virtiofs options.
        4. Log into guest then mount the virtiofs targets.
        5. Generate files or run stress on the mount points inside guest.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """
    def get_viofs_exe(session):
        """
        Get viofs.exe from virtio win iso,such as E:\viofs\2k19\amd64
        """
        logging.info("Get virtiofs exe full path.")
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
    cmd_new_folder = params.get('cmd_new_folder')
    cmd_copy_file = params.get('cmd_copy_file')
    cmd_del_folder = params.get('cmd_del_folder')

    # pjdfs test config
    cmd_pjdfstest = params.get('cmd_pjdfstest')
    cmd_unpack = params.get('cmd_unpack')
    cmd_yum_deps = params.get('cmd_yum_deps')
    cmd_autoreconf = params.get('cmd_autoreconf')
    cmd_configure = params.get('cmd_configure')
    cmd_make = params.get('cmd_make')
    pjdfstest_pkg = params.get('pjdfstest_pkg')
    username = params.get('username')
    password = params.get('password')
    port = params.get('file_transfer_port')

    # fio config
    fio_options = params.get('fio_options')
    io_timeout = params.get_numeric('io_timeout')

    # xfstest config
    cmd_xfstest = params.get('cmd_xfstest')
    fs_dest_fs2 = params.get('fs_dest_fs2')
    cmd_download_xfstest = params.get('cmd_download_xfstest')
    cmd_yum_install = params.get('cmd_yum_install')
    cmd_make_xfs = params.get('cmd_make_xfs')
    cmd_setenv = params.get('cmd_setenv')
    cmd_setenv_nfs = params.get('cmd_setenv_nfs', '')
    cmd_useradd = params.get('cmd_useradd')
    fs_dest_fs1 = params.get('fs_dest_fs1')
    cmd_get_tmpfs = params.get('cmd_get_tmpfs')
    cmd_set_tmpfs = params.get('cmd_set_tmpfs')
    size_mem1 = params.get('size_mem1')

    # xfstest-nfs config
    setup_local_nfs = params.get('setup_local_nfs')

    if cmd_xfstest:
        # /dev/shm is the default memory-backend-file, the default value is the
        # half of the host memory. Increase it to guest memory size to avoid crash
        ori_tmpfs_size = process.run(cmd_get_tmpfs, shell=True).stdout_text.replace("\n", "")
        logging.debug("original tmpfs size is %s", ori_tmpfs_size)
        params["post_command"] = cmd_set_tmpfs % ori_tmpfs_size
        params["pre_command"] = cmd_set_tmpfs % size_mem1
        if setup_local_nfs:
            for fs in params.objects("filesystems"):
                nfs_params = params.object_params(fs)
                params["export_dir"] = nfs_params.get("export_dir")
                params["nfs_mount_src"] = nfs_params.get("nfs_mount_src")
                params["nfs_mount_dir"] = nfs_params.get("fs_source_dir")
                nfs_local = nfs.Nfs(params)
                nfs_local.setup()
        params["start_vm"] = "yes"
        env_process.preprocess(test, params, env)

    os_type = params.get("os_type")
    vm = env.get_vm(params.get("main_vm"))
    vm.verify_alive()
    session = vm.wait_for_login()
    host_addr = vm.get_address()

    if os_type == "windows":
        cmd_timeout = params.get_numeric("cmd_timeout", 120)
        driver_name = params["driver_name"]
        install_path = params["install_path"]
        check_installed_cmd = params["check_installed_cmd"] % install_path

        # Check whether windows driver is running,and enable driver verifier
        session = utils_test.qemu.windrv_check_running_verifier(session,
                                                                vm, test,
                                                                driver_name)
        # install winfsp tool
        error_context.context("Install winfsp for windows guest.",
                              logging.info)
        installed = session.cmd_status(check_installed_cmd) == 0
        if installed:
            logging.info("Winfsp tool is already installed.")
        else:
            install_cmd = utils_misc.set_winutils_letter(session,
                                                         params["install_cmd"])
            session.cmd(install_cmd, cmd_timeout)
            if not utils_misc.wait_for(lambda: not session.cmd_status(
                    check_installed_cmd), 60):
                test.error("Winfsp tool is not installed.")

    for fs in params.objects("filesystems"):
        fs_params = params.object_params(fs)
        fs_target = fs_params.get("fs_target")
        fs_dest = fs_params.get("fs_dest")

        fs_source = fs_params.get("fs_source_dir")
        base_dir = fs_params.get("fs_source_base_dir",
                                 data_dir.get_data_dir())
        if not os.path.isabs(fs_source):
            fs_source = os.path.join(base_dir, fs_source)

        host_data = os.path.join(fs_source, 'fs_test')

        if os_type == "linux":
            error_context.context("Create a destination directory %s "
                                  "inside guest." % fs_dest, logging.info)
            utils_misc.make_dirs(fs_dest, session)
            if not cmd_xfstest:
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

            logging.info("Query virtiofs service status.")
            status, output = session.cmd_status_output(viofs_sc_query_cmd)
            if "not exist as an installed service" in output:
                logging.info("Register virtiofs service in windows guest.")
                exe_path = get_viofs_exe(session)
                viofs_sc_create_cmd = viofs_sc_create_cmd % exe_path
                sc_create_s, sc_create_o = session.cmd_status_output(viofs_sc_create_cmd)
                if sc_create_s != 0:
                    test.fail("Failed to register virtiofs service, output is %s" % sc_create_o)
            elif "RUNNING" not in output:
                logging.info("Start virtiofs service.")
                sc_start_s, sc_start_o = session.cmd_status_output(viofs_sc_start_cmd)
                if sc_start_s != 0:
                    test.fail("Failed to start virtiofs service, output is %s" % sc_start_o)
            else:
                logging.info("Virtiofs service is running.")

            viofs_log_file_cmd = params.get("viofs_log_file_cmd")
            if viofs_log_file_cmd:
                error_context.context("Check if LOG file is created.", logging.info)
                log_dir_s = session.cmd_status(viofs_log_file_cmd)
                if log_dir_s != 0:
                    test.fail("Virtiofs log is not created.")

            # get fs dest for vm
            virtio_fs_disk_label = fs_target
            error_context.context("Get Volume letter of virtio fs target, the disk"
                                  "lable is %s." % virtio_fs_disk_label,
                                  logging.info)
            vol_con = "VolumeName='%s'" % virtio_fs_disk_label
            vol_func = utils_misc.get_win_disk_vol(session, condition=vol_con)
            volume_letter = utils_misc.wait_for(lambda: vol_func, cmd_timeout)
            fs_dest = "%s:" % volume_letter

        guest_file = os.path.join(fs_dest, 'fs_test')
        logging.info("The guest file in shared dir is %s", guest_file)

        try:
            if cmd_dd:
                error_context.context("Creating file under %s inside "
                                      "guest." % fs_dest, logging.info)
                session.cmd(cmd_dd % guest_file, io_timeout)

                if os_type == "linux":
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

            if cmd_new_folder and cmd_copy_file and cmd_del_folder:
                error_context.context("Folder test under %s inside "
                                      "guest." % fs_dest, logging.info)
                session.cmd(cmd_new_folder % fs_dest)
                test_file = guest_file if os_type == "linux" \
                    else "%s:\\%s" % (volume_letter, 'fs_test')
                session.cmd(cmd_copy_file % (test_file, fs_dest))
                session.cmd(cmd_del_folder % fs_dest)

            if fio_options:
                error_context.context("Run fio on %s." % fs_dest, logging.info)
                fio = generate_instance(params, vm, 'fio')
                try:
                    fio.run(fio_options % guest_file, io_timeout)
                finally:
                    fio.clean()
                vm.verify_dmesg()

            if cmd_pjdfstest:
                error_context.context("Run pjdfstest on %s." % fs_dest, logging.info)
                host_path = os.path.join(data_dir.get_deps_dir('pjdfstest'), pjdfstest_pkg)
                scp_to_remote(host_addr, port, username, password, host_path, fs_dest)
                session.cmd(cmd_unpack.format(fs_dest), 180)
                session.cmd(cmd_yum_deps, 180)
                session.cmd(cmd_autoreconf % fs_dest, 180)
                session.cmd(cmd_configure.format(fs_dest), 180)
                session.cmd(cmd_make % fs_dest, io_timeout)
                session.cmd(cmd_pjdfstest % fs_dest, io_timeout)

            if cmd_xfstest:
                error_context.context("Run xfstest on guest.", logging.info)
                utils_misc.make_dirs(fs_dest_fs2, session)
                if session.cmd_status(cmd_download_xfstest, 360):
                    test.error("Failed to download xfstests-dev")
                session.cmd(cmd_yum_install, 180)
                session.cmd(cmd_make_xfs, 360)
                session.cmd(cmd_setenv, 180)
                session.cmd(cmd_setenv_nfs, 180)
                session.cmd(cmd_useradd, 180)

                try:
                    output = session.cmd_output(cmd_xfstest, io_timeout)
                    logging.info("%s", output)
                    if 'Failed' in output:
                        test.fail('The xfstest failed.')
                    else:
                        break
                except (aexpect.ShellStatusError, aexpect.ShellTimeoutError):
                    test.fail('The xfstest failed.')

        finally:
            if os_type == "linux":
                utils_disk.umount(fs_target, fs_dest, 'virtiofs', session=session)
                utils_misc.safe_rmdir(fs_dest, session=session)
            if setup_local_nfs:
                session.close()
                vm.destroy()
                for fs in params.objects("filesystems"):
                    nfs_params = params.object_params(fs)
                    params["export_dir"] = nfs_params.get("export_dir")
                    params["nfs_mount_dir"] = nfs_params.get("fs_source_dir")
                    params["rm_export_dir"] = nfs_params.get("export_dir")
                    params["rm_mount_dir"] = nfs_params.get("fs_source_dir")
                    nfs_local = nfs.Nfs(params)
                    nfs_local.cleanup()
                    utils_misc.safe_rmdir(params["export_dir"])

    # during all virtio fs is mounted, reboot vm
    if params.get('reboot_guest', 'no') == 'yes':
        def get_vfsd_num():
            """
            Get virtiofsd daemon number during vm boot up.
            :return: virtiofsd daemon count.
            """
            cmd_ps_virtiofsd = params.get('cmd_ps_virtiofsd')
            vfsd_num = 0
            for device in vm.devices:
                if isinstance(device, qdevices.QVirtioFSDev):
                    sock_path = device.get_param('sock_path')
                    cmd_ps_virtiofsd = cmd_ps_virtiofsd % sock_path
                    vfsd_ps = process.system_output(cmd_ps_virtiofsd, shell=True)
                    vfsd_num += len(vfsd_ps.strip().splitlines())
            return vfsd_num

        error_context.context("Check virtiofs daemon before reboot vm.",
                              logging.info)

        vfsd_num_bf = get_vfsd_num()
        error_context.context("Reboot guest and check virtiofs daemon.",
                              logging.info)
        vm.reboot()
        if not vm.is_alive():
            test.fail("After rebooting vm quit unexpectedly.")
        vfsd_num_af = get_vfsd_num()

        if vfsd_num_bf != vfsd_num_af:
            test.fail("Virtiofs daemon is different before and after reboot.\n"
                      "Before reboot: %s\n"
                      "After reboot: %s\n", (vfsd_num_bf, vfsd_num_af))
