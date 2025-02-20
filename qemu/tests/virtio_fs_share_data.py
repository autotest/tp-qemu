import os
import re
import time

import aexpect
from avocado.utils import process
from virttest import (
    data_dir,
    env_process,
    error_context,
    nfs,
    utils_disk,
    utils_misc,
    utils_selinux,
    utils_test,
)
from virttest.qemu_devices import qdevices
from virttest.remote import scp_to_remote
from virttest.utils_windows import virtio_win

from provider import virtio_fs_utils, win_driver_utils
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

    def get_stdev(file):
        """
        Get file's st_dev value.
        """
        stdev = session.cmd_output(cmd_get_stdev % file).strip()
        test.log.info("%s device id is %s.", file, stdev)
        return stdev

    def check_socket_group():
        """
        check socket path's user group
        """
        cmd_get_sock = params["cmd_get_sock"]
        for device in vm.devices:
            if isinstance(device, qdevices.QVirtioFSDev):
                sock_path = device.get_param("sock_path")
                break
        sock_path_info = process.system_output(cmd_get_sock % sock_path)
        group_name = (
            sock_path_info.decode(encoding="utf-8", errors="strict").strip().split()[3]
        )
        if group_name != socket_group:
            test.fail(
                "Socket-group name is not correct.\nIt should be %s,but"
                " the output is %s" % (socket_group, group_name)
            )

    def is_autoit_finished(session, process_name):
        """
        Check whether the target process is finished running
        """
        check_proc_cmd = check_proc_temp % process_name
        status, output = session.cmd_status_output(check_proc_cmd)
        if status:
            return False
        return "autoit3" not in output.lower()

    def viofs_svc_create(cmd):
        """
        Only for windows guest, to create a virtiofs service.

        :param cmd: cmd to create virtiofs service
        """
        test.log.info("Register virtiofs service in Windows guest.")
        exe_path = get_viofs_exe(session)
        # copy virtiofs.exe to c: in case the virtio-win cdrom volume name
        # is changed in other cases of a loop.
        session.cmd(params.get("viofs_exe_copy_cmd") % exe_path)
        sc_create_s, sc_create_o = session.cmd_status_output(cmd)
        if sc_create_s != 0:
            test.fail("Failed to register virtiofs service, output is %s" % sc_create_o)

    def viofs_svc_stop_start(action, cmd, expect_status):
        """
        Only for windows guest, to start/stop VirtioFsSvc.

        :param action: stop or start.
        :param cmd: cmd to start or stop virtiofs service
        :param expect_status: RUNNING or STOPPED.
        """
        error_context.context("Try to %s VirtioFsSvc service." % action, test.log.info)
        session.cmd(cmd)
        output = session.cmd_output(viofs_sc_query_cmd)  # pylint: disable=E0606
        if expect_status not in output:
            test.fail(
                "Could not %s VirtioFsSvc service, " "detail: '%s'" % (action, output)
            )

    def start_multifs_instance():
        """
        Only for windows and only for multiple shared directory.
        """
        error_context.context(
            "MultiFS-%s: Start virtiofs instance with"
            " tag %s to %s." % (fs, fs_target, fs_volume_label),
            test.log.info,
        )
        instance_start_cmd = params["instance_start_cmd"]
        output = session.cmd_output(
            instance_start_cmd % (fs_target, fs_target, fs_volume_label)
        )
        if re.search("KO.*error", output, re.I):
            test.fail(
                "MultiFS-%s: Start virtiofs instance failed, "
                "output is %s." % (fs, output)
            )

    # data io config
    test_file = params.get("test_file")
    folder_test = params.get("folder_test")
    cmd_dd = params.get("cmd_dd")
    cmd_md5 = params.get("cmd_md5")
    cmd_new_folder = params.get("cmd_new_folder")
    cmd_copy_file = params.get("cmd_copy_file")
    cmd_rename_folder = params.get("cmd_rename_folder")
    cmd_check_folder = params.get("cmd_check_folder")
    cmd_del_folder = params.get("cmd_del_folder")

    # soft link config
    cmd_symblic_file = params.get("cmd_symblic_file")
    cmd_symblic_folder = params.get("cmd_symblic_folder")
    file_link = params.get("file_link")
    folder_link = params.get("folder_link")

    # pjdfs test config
    cmd_pjdfstest = params.get("cmd_pjdfstest")
    cmd_unpack = params.get("cmd_unpack")
    cmd_yum_deps = params.get("cmd_yum_deps")
    cmd_autoreconf = params.get("cmd_autoreconf")
    cmd_configure = params.get("cmd_configure")
    cmd_make = params.get("cmd_make")
    pjdfstest_pkg = params.get("pjdfstest_pkg")
    username = params.get("username")
    password = params.get("password")
    port = params.get("file_transfer_port")

    # fio config
    fio_options = params.get("fio_options")
    io_timeout = params.get_numeric("io_timeout")

    # iozone config
    iozone_options = params.get("iozone_options")

    # xfstest config
    cmd_xfstest = params.get("cmd_xfstest")
    fs_dest_fs2 = params.get("fs_dest_fs2")
    cmd_download_xfstest = params.get("cmd_download_xfstest")
    cmd_yum_install = params.get("cmd_yum_install")
    cmd_make_xfs = params.get("cmd_make_xfs")
    cmd_setenv = params.get("cmd_setenv")
    cmd_setenv_nfs = params.get("cmd_setenv_nfs", "")
    cmd_useradd = params.get("cmd_useradd")
    cmd_get_tmpfs = params.get("cmd_get_tmpfs")
    cmd_set_tmpfs = params.get("cmd_set_tmpfs")
    size_mem1 = params.get("size_mem1")

    # git init config
    git_init_cmd = params.get("git_init_cmd")
    install_git_cmd = params.get("install_git_cmd")
    check_proc_temp = params.get("check_proc_temp")
    git_check_cmd = params.get("git_check_cmd")
    autoit_name = params.get("autoit_name")

    # create dir by winapi config
    create_dir_winapi_cmd = params.get("create_dir_winapi_cmd")
    check_winapi_dir_cmd = params.get("check_winapi_dir_cmd")

    # selinux label test config
    security_label_test = params.get("security_label_test")
    getfattr_cmd = params.get("getfattr_cmd")
    context_pattern = params.get("context_pattern")
    selinux_xattr_name = params.get("selinux_xattr_name")
    trust_selinux_attr_name = params.get("trust_selinux_attr_name")
    se_mode = params.get("security_mode")

    # winfsp test config
    winfsp_copy_cmd = params.get("winfsp_copy_cmd")
    winfsp_test_cmd = params.get("winfsp_test_cmd")

    # selinux-testsuits config
    cmd_download_selinux_suits = params.get("cmd_download_selinux_suits")
    cmd_yum_install_se = params.get("cmd_yum_install_se")
    jfsutils_pkg = params.get("jfsutils_pkg")
    cmd_install_jfsutils = params.get("cmd_install_jfsutils")
    cmd_make_sesuit = params.get("cmd_make_sesuit")
    timeout_make_sesuit = params.get_numeric("timeout_make_sesuit")
    make_blacklist = params.get("make_blacklist")
    cmd_run_sesuit = params.get("cmd_run_sesuit")

    # nfs config
    setup_local_nfs = params.get("setup_local_nfs")

    setup_hugepages = params.get("setup_hugepages", "no") == "yes"
    socket_group_test = params.get("socket_group_test", "no") == "yes"
    socket_group = params.get("socket_group")

    # setup_filesystem_on_host
    setup_filesystem_on_host = params.get("setup_filesystem_on_host")

    # case insensitive test
    case_insensitive_test = params.get("case_insensitive_test")
    viofs_case_insense_enable_cmd = params.get("viofs_case_insense_enable_cmd")

    # st_dev check config
    cmd_get_stdev = params.get("cmd_get_stdev")
    nfs_mount_dst_name = params.get("nfs_mount_dst_name")
    if cmd_xfstest and not setup_hugepages:
        # /dev/shm is the default memory-backend-file, the default value is the
        # half of the host memory. Increase it to guest memory size to avoid crash
        ori_tmpfs_size = process.run(cmd_get_tmpfs, shell=True).stdout_text.replace(
            "\n", ""
        )
        test.log.debug("original tmpfs size is %s", ori_tmpfs_size)
        params["post_command"] = cmd_set_tmpfs % ori_tmpfs_size
        params["pre_command"] = cmd_set_tmpfs % size_mem1

    if setup_local_nfs:
        nfs_local_dic = {}
        for fs in params.objects("filesystems"):
            nfs_params = params.object_params(fs)

            params["export_dir"] = nfs_params.get("export_dir")
            params["nfs_mount_src"] = nfs_params.get("nfs_mount_src")
            params["nfs_mount_dir"] = nfs_params.get("fs_source_dir")
            if cmd_get_stdev:
                fs_source_dir = nfs_params.get("fs_source_dir")
                params["nfs_mount_dir"] = os.path.join(
                    fs_source_dir, nfs_mount_dst_name
                )
            nfs_local = nfs.Nfs(params)
            nfs_local.setup()
            nfs_local_dic[fs] = nfs_local

    if setup_filesystem_on_host:
        # create partition on host
        dd_of_on_host = params.get("dd_of_on_host")
        cmd_dd_on_host = params.get("cmd_dd_on_host")
        process.system(cmd_dd_on_host % dd_of_on_host, timeout=300)

        cmd_losetup_query_on_host = params.get("cmd_losetup_query_on_host")
        loop_device = (
            process.run(cmd_losetup_query_on_host, timeout=60).stdout.decode().strip()
        )
        if not loop_device:
            test.fail("Can't find a valid loop device! ")
        # loop device setups on host
        cmd_losetup_on_host = params.get("cmd_losetup_on_host")
        process.system(cmd_losetup_on_host % dd_of_on_host, timeout=60)
        # make filesystem on host
        fs_on_host = params.get("fs_on_host")
        cmd_mkfs_on_host = params.get("cmd_mkfs_on_host")
        cmd_mkfs_on_host = cmd_mkfs_on_host % str(fs_on_host)
        cmd_mkfs_on_host = cmd_mkfs_on_host + loop_device
        process.system(cmd_mkfs_on_host, timeout=60)
        # mount on host
        fs_source = params.get("fs_source_dir")
        base_dir = params.get("fs_source_base_dir", data_dir.get_data_dir())
        if not os.path.isabs(fs_source):
            fs_source = os.path.join(base_dir, fs_source)
        if not utils_misc.check_exists(fs_source):
            utils_misc.make_dirs(fs_source)
        if not utils_disk.mount(loop_device, fs_source):
            test.fail("Fail to mount on host! ")

    if security_label_test:
        # make sure selinux is enabled on host before sucurity label test.
        error_context.context(
            "Set selinux to %s status on host before"
            " starting virtiofsd and vm." % se_mode,
            test.log.info,
        )
        se_mode_host_before = utils_selinux.get_status()
        if se_mode_host_before.lower() != se_mode:
            try:
                utils_selinux.set_status(se_mode)
            except Exception as err_msg:
                test.cancel("Setting selinux failed on host with" " %s." % str(err_msg))
    try:
        vm = None
        if (
            cmd_xfstest
            or setup_local_nfs
            or setup_hugepages
            or setup_filesystem_on_host
            or security_label_test
        ):
            params["start_vm"] = "yes"
            env_process.preprocess(test, params, env)

        os_type = params.get("os_type")
        vm = env.get_vm(params.get("main_vm"))
        vm.verify_alive()
        session = vm.wait_for_login()
        host_addr = vm.get_address()

        if socket_group_test:
            check_socket_group()

        if security_label_test and os_type == "linux":
            # make sure selinux is enabled on guest.
            error_context.context(
                "Set selinux to %s status on" " guest." % se_mode, test.log.info
            )
            se_mode_guest_before = session.cmd_output("getenforce").strip()
            if se_mode_guest_before != se_mode:
                test.log.info("Need to change selinux mode to %s.", se_mode)
                if se_mode_guest_before == "disabled":
                    cmd = "sed -i 's/^SELINUX=.*/SELINUX=%s/g'" % se_mode
                    cmd += " /etc/selinux/config"
                    session.cmd(cmd)
                    session = vm.reboot(session)
                if se_mode_guest_before == "permissive":
                    session.cmd("setenforce %s" % se_mode)

        if os_type == "windows":
            cmd_timeout = params.get_numeric("cmd_timeout", 120)
            driver_name = params["driver_name"]
            # Check whether windows driver is running,and enable driver verifier
            session = utils_test.qemu.windrv_check_running_verifier(
                session, vm, test, driver_name
            )
            # create virtiofs service
            viofs_svc_name = params["viofs_svc_name"]
            virtio_fs_utils.create_viofs_service(
                test, params, session, service=viofs_svc_name
            )
            viofs_svc_name = params.get("viofs_svc_name", "VirtioFsSvc")
        for fs in params.objects("filesystems"):
            fs_params = params.object_params(fs)
            fs_target = fs_params.get("fs_target")
            fs_dest = fs_params.get("fs_dest")
            fs_volume_label = fs_params.get("volume_label")
            fs_source = fs_params.get("fs_source_dir")
            base_dir = fs_params.get("fs_source_base_dir", data_dir.get_data_dir())
            if not os.path.isabs(fs_source):
                fs_source = os.path.join(base_dir, fs_source)

            host_data = os.path.join(fs_source, test_file)

            if os_type == "linux":
                error_context.context(
                    "Create a destination directory %s " "inside guest." % fs_dest,
                    test.log.info,
                )
                utils_misc.make_dirs(fs_dest, session)
                if not cmd_xfstest:
                    error_context.context(
                        "Mount virtiofs target %s to %s inside"
                        " guest." % (fs_target, fs_dest),
                        test.log.info,
                    )
                    if not utils_disk.mount(
                        fs_target, fs_dest, "virtiofs", session=session
                    ):
                        test.fail("Mount virtiofs target failed.")
            else:
                if params.get("viofs_svc_name", "VirtioFsSvc") == "VirtioFsSvc":
                    error_context.context(
                        "Start virtiofs service in guest.", test.log.info
                    )
                    debug_log_operation = params.get("debug_log_operation")
                    if debug_log_operation:
                        session = virtio_fs_utils.operate_debug_log(
                            test, params, session, vm, debug_log_operation
                        )
                    virtio_fs_utils.start_viofs_service(test, params, session)
                else:
                    error_context.context(
                        "Start winfsp.launcher" " instance in guest.", test.log.info
                    )
                    start_multifs_instance()

                # get fs dest for vm
                virtio_fs_disk_label = fs_target
                error_context.context(
                    "Get Volume letter of virtio fs target, the disk"
                    "lable is %s." % virtio_fs_disk_label,
                    test.log.info,
                )
                vol_con = "VolumeName='%s'" % virtio_fs_disk_label
                volume_letter = utils_misc.wait_for(
                    lambda: utils_misc.get_win_disk_vol(session, condition=vol_con),
                    cmd_timeout,  # pylint: disable=E0606
                )
                if volume_letter is None:
                    test.fail("Could not get virtio-fs mounted volume letter.")
                fs_dest = "%s:" % volume_letter

            guest_file = os.path.join(fs_dest, test_file)
            test.log.info("The guest file in shared dir is %s", guest_file)

            try:
                if cmd_dd:
                    error_context.context(
                        "Creating file under %s inside " "guest." % fs_dest,
                        test.log.info,
                    )
                    # for windows, after virtiofs service start up, should wait
                    #  for the volume active.
                    if os_type == "windows":
                        pattern = r"The system cannot find the file specified"
                        end_time = time.time() + io_timeout
                        while time.time() < end_time:
                            status, output = session.cmd_status_output(
                                cmd_dd % guest_file
                            )
                            if re.findall(pattern, output, re.M | re.I):
                                time.sleep(2)
                                continue
                            if status != 0:
                                test.fail("dd command failed on virtiofs.")
                            break
                        else:
                            test.error(
                                f"Volume is not ready for io within {io_timeout}."
                            )
                    else:
                        session.cmd(cmd_dd % guest_file, io_timeout)

                    if os_type == "linux":
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

                    viofs_log_file_cmd = params.get("viofs_log_file_cmd")
                    if viofs_log_file_cmd:
                        error_context.context(
                            "Check if LOG file is created.", test.log.info
                        )
                        log_dir_s = session.cmd_status(viofs_log_file_cmd)
                        if log_dir_s != 0:
                            test.fail("Virtiofs log is not created.")

                if folder_test == "yes":
                    error_context.context(
                        "Folder test under %s inside " "guest." % fs_dest, test.log.info
                    )
                    session.cmd(cmd_new_folder % fs_dest)
                    try:
                        session.cmd(cmd_copy_file)
                        session.cmd(cmd_rename_folder)
                        session.cmd(cmd_del_folder)
                        status = session.cmd_status(cmd_check_folder)
                        if status == 0:
                            test.fail("The folder are not deleted.")
                    finally:
                        if os_type == "linux":
                            session.cmd("cd -")
                        else:
                            session.cmd("cd /d C:\\")

                if case_insensitive_test:
                    # only for windows guest, testing case insensitive
                    def file_check(cmd):
                        s, o = session.cmd_status_output(cmd, io_timeout)
                        if s:
                            test.fail(
                                "Case insensitive failed," " the output is %s" % o
                            )

                    error_context.context(
                        "Check if case insensitive is set in registry.", test.log.info
                    )
                    cmd = params.get("viofs_reg_query_cmd")
                    ret = session.cmd_output(cmd)
                    if "caseinsensitive" not in ret.lower():
                        s, o = session.cmd_status_output(viofs_case_insense_enable_cmd)
                        if s:
                            test.fail(
                                "Fail to set virtiofs case insensitive,"
                                " output is %s" % o
                            )
                        else:
                            error_context.context("Reboot guest.", test.log.info)
                            session = vm.reboot()

                    error_context.context(
                        "Creating file and file name contain "
                        "uppercase letter in guest.",
                        test.log.info,
                    )
                    test_file_guest = test_file + "_Guest"
                    guest_file = os.path.join(fs_dest, test_file_guest)
                    session.cmd("echo hello > %s" % guest_file, io_timeout)

                    error_context.context(
                        "check the file with" " uppercase letter name.", test.log.info
                    )
                    guest_file_full_path = (
                        volume_letter + ":\\" + test_file_guest.upper()
                    )
                    cmd_check_file = "dir %s" % guest_file_full_path
                    file_check(cmd_check_file)
                    cmd_check_md5sum = cmd_md5 % (
                        volume_letter,
                        test_file_guest.upper(),
                    )
                    file_check(cmd_check_md5sum)

                    error_context.context("Create file on host.", test.log.info)
                    test_file_host = test_file + "_Host"
                    host_data = os.path.join(fs_source, test_file_host)
                    process.system("touch %s" % host_data, io_timeout)
                    time.sleep(2)
                    error_context.context(
                        "check the file with" " lowercase letter name.", test.log.info
                    )
                    guest_file_full_path = (
                        volume_letter + ":\\" + test_file_host.lower()
                    )
                    cmd_check_file = "dir %s" % guest_file_full_path
                    file_check(cmd_check_file)
                    cmd_check_md5sum = cmd_md5 % (volume_letter, test_file_host.lower())
                    file_check(cmd_check_md5sum)

                if cmd_symblic_file:
                    error_context.context(
                        "Symbolic test under %s inside " "guest." % fs_dest,
                        test.log.info,
                    )
                    cmd_create_file = params["cmd_create_file"]
                    session.cmd(cmd_new_folder % fs_dest)
                    session.cmd(cmd_create_file)
                    session.cmd(cmd_copy_file)
                    if session.cmd_status(cmd_symblic_file):
                        test.fail("Creat symbolic files failed.")
                    if session.cmd_status(cmd_symblic_folder):
                        test.fail("Creat symbolic folders failed.")

                    error_context.context(
                        "Compare symbolic link info in " "the host and guest",
                        test.log.info,
                    )

                    def __file_check(file, os_type):
                        cmd_map = {
                            "win_host": "cat %s",
                            "win_guest": "type %s",
                            "linux_host": "ls -l %s",
                            "linux_guest": "ls -l %s",
                        }
                        if "guest" in os_type:
                            o = session.cmd_output(cmd_map[os_type] % file)
                        else:
                            o = process.run(cmd_map[os_type] % file).stdout_text
                        return o.strip().split()[-1]

                    if os_type == "linux":
                        file_link_host = os.path.join(fs_source, file_link)
                        if __file_check(file_link, "linux_guest") != __file_check(
                            file_link_host, "linux_host"
                        ):
                            test.fail(
                                "Symbolic file configured in host "
                                "and guest are inconsistent"
                            )
                        folder_link_host = os.path.join(fs_source, folder_link)
                        if __file_check(folder_link, "linux_guest") != __file_check(
                            folder_link_host, "linux_host"
                        ):
                            test.fail(
                                "Symbolic folder configured in "
                                "host and guest are inconsistent"
                            )
                        session.cmd("cd -")
                    else:
                        content = session.cmd_output("type %s" % test_file).strip()
                        link_guest = __file_check(file_link, "win_guest")
                        file_link_host = os.path.join(fs_source, file_link)
                        link_host = __file_check(file_link_host, "win_host")
                        if link_guest != content or link_host != content:
                            test.fail(
                                "Symbolic file check failed,"
                                " the real content is %s\n"
                                "the link file content in guest is %s\n"
                                "the link file content in host is %s."
                                % (content, link_guest, link_host)
                            )
                        # check the file in folder link
                        folder_link_guest = folder_link + "\\" + test_file
                        link_guest = __file_check(folder_link_guest, "win_guest")
                        folder_link_host = os.path.join(
                            fs_source, folder_link, test_file
                        )
                        link_host = __file_check(folder_link_host, "win_host")
                        if link_guest != content or link_host != content:
                            test.fail(
                                "Symbolic folder check failed,"
                                " the real content is %s\n"
                                "the link file content in guest is %s\n"
                                "the link file content in host is %s."
                                % (content, link_guest, link_host)
                            )
                        session.cmd("cd /d C:\\")

                if fio_options:
                    error_context.context("Run fio on %s." % fs_dest, test.log.info)
                    fio = generate_instance(params, vm, "fio")
                    try:
                        for bs in params.get_list("stress_bs"):
                            fio.run(fio_options % (guest_file, bs), io_timeout)
                    finally:
                        fio.clean()
                    vm.verify_dmesg()

                if iozone_options:
                    error_context.context(
                        "Run iozone test on %s." % fs_dest, test.log.info
                    )
                    io_test = generate_instance(params, vm, "iozone")
                    try:
                        for bs in params.get_list("stress_bs"):
                            io_test.run(iozone_options % (bs, guest_file), io_timeout)
                    finally:
                        io_test.clean()

                if cmd_pjdfstest:
                    error_context.context(
                        "Run pjdfstest on %s." % fs_dest, test.log.info
                    )
                    host_path = os.path.join(
                        data_dir.get_deps_dir("pjdfstest"), pjdfstest_pkg
                    )
                    scp_to_remote(
                        host_addr, port, username, password, host_path, fs_dest
                    )
                    session.cmd(cmd_unpack.format(fs_dest), 180)
                    session.cmd(cmd_yum_deps, 180)
                    session.cmd(cmd_autoreconf % fs_dest, 180)
                    session.cmd(cmd_configure.format(fs_dest), 180)
                    session.cmd(cmd_make % fs_dest, io_timeout)
                    status, output = session.cmd_status_output(
                        cmd_pjdfstest % fs_dest, io_timeout
                    )
                    failed_test = output.split("-------------------")[1].split(
                        "Files="
                    )[0]
                    # ignore the specific failed cases from pjdfstest
                    ignore_cases = params.objects("pjdfstest_blacklist")
                    matched_element = params.get("fs_dest", "/mnt") + r".*\.t"
                    cases_in_output = list(re.findall(matched_element, failed_test))
                    false_in_list = [False for _ in range(len(cases_in_output))]
                    cases_in_output = dict(zip(cases_in_output, false_in_list))
                    for case in cases_in_output.keys():
                        for ig_case in ignore_cases:
                            if ig_case in case:
                                error_context.context(
                                    "Warn: %s was failed!" % ig_case, test.log.debug
                                )
                                cases_in_output[case] = True

                    unexpected_fail_case = list(cases_in_output.values()).count(False)

                    if status != 0 and unexpected_fail_case > 0:
                        test.log.info(output)
                        test.fail("The pjdfstest failed.")

                if cmd_xfstest:
                    error_context.context("Run xfstest on guest.", test.log.info)
                    utils_misc.make_dirs(fs_dest_fs2, session)
                    if session.cmd_status(cmd_download_xfstest, 360):
                        test.error("Failed to download xfstests-dev")
                    session.cmd(cmd_yum_install, 180)

                    # Due to the increase of xfstests-dev cases, more time is
                    # needed for compilation here.
                    status, output = session.cmd_status_output(cmd_make_xfs, 900)
                    if status != 0:
                        test.log.info(output)
                        test.error("Failed to build xfstests-dev")
                    session.cmd(cmd_setenv, 180)
                    session.cmd(cmd_setenv_nfs, 180)
                    session.cmd(cmd_useradd, 180)

                    try:
                        output = session.cmd_output(cmd_xfstest, io_timeout)
                        test.log.info("%s", output)
                        if "Failed" in output:
                            test.fail("The xfstest failed.")
                        else:
                            break
                    except (aexpect.ShellStatusError, aexpect.ShellTimeoutError):
                        test.fail("The xfstest failed.")

                if cmd_get_stdev:
                    error_context.context(
                        "Create files in local device and" " nfs device ", test.log.info
                    )
                    file_in_local_host = os.path.join(fs_source, "file_test")
                    file_in_nfs_host = os.path.join(
                        fs_source, nfs_mount_dst_name, "file_test"
                    )
                    cmd_touch_file = "touch %s && touch %s" % (
                        file_in_local_host,
                        file_in_nfs_host,
                    )
                    process.run(cmd_touch_file)
                    error_context.context(
                        "Check if the two files' st_dev are" " the same on guest.",
                        test.log.info,
                    )
                    file_in_local_guest = os.path.join(fs_dest, "file_test")
                    file_in_nfs_guest = os.path.join(
                        fs_dest, nfs_mount_dst_name, "file_test"
                    )
                    if get_stdev(file_in_local_guest) == get_stdev(file_in_nfs_guest):
                        test.fail("st_dev are the same on diffrent device.")

                if git_init_cmd:
                    if os_type == "windows":
                        error_context.context("Install git", test.log.info)
                        check_status, check_output = session.cmd_status_output(
                            git_check_cmd
                        )
                        if (
                            check_status
                            and "not recognized" in check_output
                            or "cannot find the path" in check_output
                        ):
                            install_git_cmd = utils_misc.set_winutils_letter(
                                session, install_git_cmd
                            )
                            status, output = session.cmd_status_output(install_git_cmd)

                            if status:
                                test.error(
                                    "Failed to install git, status=%s, output=%s"
                                    % (status, output)
                                )
                            test.log.info("Wait for git installation to complete")
                            utils_misc.wait_for(
                                lambda: is_autoit_finished(session, autoit_name),
                                360,
                                60,
                                5,
                            )
                    error_context.context(
                        "Git init test in %s" % fs_dest, test.log.info
                    )
                    status, output = session.cmd_status_output(git_init_cmd % fs_dest)
                    if status:
                        test.fail("Git init failed with %s" % output)

                if create_dir_winapi_cmd:
                    error_context.context(
                        "Create new directory with WinAPI's " "CreateDirectory.",
                        test.log.info,
                    )
                    session.cmd(create_dir_winapi_cmd % fs_dest)

                    ret = utils_misc.wait_for(
                        lambda: not bool(
                            session.cmd_status(check_winapi_dir_cmd % fs_dest)
                        ),
                        timeout=60,
                    )
                    if not ret:
                        test.fail(
                            "Create dir failed in 60s, output is %s"
                            % session.cmd_output(check_winapi_dir_cmd % fs_dest)
                        )

                    error_context.context("Get virtiofsd log file.", test.log.info)
                    vfsd_dev = vm.devices.get_by_params({"source": fs_source})[0]
                    vfd_log_name = "%s-%s.log" % (
                        vfsd_dev.get_qid(),
                        vfsd_dev.get_param("name"),
                    )
                    vfd_logfile = utils_misc.get_log_filename(vfd_log_name)

                    error_context.context("Check virtiofsd log.", test.log.info)
                    pattern = r"Replying ERROR.*header.*OutHeader.*error.*-9"
                    with open(vfd_logfile, "r") as f:
                        for line in f.readlines():
                            if re.match(pattern, line, re.I):
                                test.fail(
                                    "CreateDirectory cause virtiofsd-rs ERROR reply."
                                )

                if getfattr_cmd:
                    # testing security label.
                    def check_attribute(object, xattr, get_type=True, side="guest"):
                        """
                        Check if attribute is set accordingly,and then
                        get file security context type if needed.
                        :param object: file or folder
                        :param xattr: attribute name
                        :param get_type: return context type or not
                        :return: context type
                        """
                        format = xattr + "=" + context_pattern
                        full_pattern = re.compile(r"%s" % format)
                        if side == "host":
                            xattr_content = (
                                process.system_output(
                                    getfattr_cmd % (xattr, object), shell=True
                                )
                                .decode()
                                .strip()
                            )
                            result = re.search(full_pattern, xattr_content)
                        if side == "guest":
                            xattr_content = session.cmd_output(
                                getfattr_cmd % (xattr, object)
                            )
                            result = re.search(full_pattern, xattr_content)
                        if not result:  # pylint: disable=E0606
                            test.fail(
                                "Attribute is not correct, the pattern is %s\n"
                                " the attribute is %s." % (full_pattern, xattr_content)
                            )
                        if get_type:
                            return result.group(1)

                    def check_security_label(file, folder, xattr_name):
                        """
                        Make sure file context type is the same with it's folder.
                        only for shared folder in guest as the attribute name is
                        remapped to others.
                        :param file: file
                        :param folder: folder
                        :param xattr_name: attribute name
                        """
                        context_type_file = check_attribute(file, xattr_name)
                        context_type_folder = check_attribute(folder, xattr_name)
                        if not context_type_file == context_type_folder:
                            test.fail(
                                "Context type isn't correct.\n"
                                "File context type is %s\n"
                                "Shared folder context type is %s"
                                % (context_type_file, context_type_folder)
                            )

                    test.log.info("Security.selinux xattr check with xattr mapping.")
                    error_context.context(
                        "Create a new file inside guest.", test.log.info
                    )
                    file_new_in_guest = os.path.join(fs_dest, "file_guest")
                    file_share_in_host = os.path.join(fs_source, "file_guest")
                    session.cmd("touch %s" % file_new_in_guest)
                    time.sleep(1)

                    error_context.context(
                        "Check new file's security label" " on guest.", test.log.info
                    )
                    check_security_label(file_new_in_guest, fs_dest, selinux_xattr_name)

                    error_context.context(
                        "Check new file's attribute on" " host.", test.log.info
                    )
                    check_attribute(
                        file_share_in_host,
                        trust_selinux_attr_name,
                        get_type=False,
                        side="host",
                    )

                    error_context.context(
                        "Create a new file inside host.", test.log.info
                    )
                    file_new_in_host = os.path.join(fs_source, "file_host")
                    file_share_in_guest = os.path.join(fs_dest, "file_host")
                    process.run("touch %s" % file_new_in_host, timeout=60)
                    time.sleep(1)
                    check_security_label(
                        file_share_in_guest, fs_dest, selinux_xattr_name
                    )

                    error_context.context(
                        "The list of xattr for the file is empty "
                        "in guest, let's check it.",
                        test.log.info,
                    )
                    getfattr_list_cmd = params.get("getfattr_list_cmd")
                    s, o = session.cmd_status_output(
                        getfattr_list_cmd % file_new_in_guest
                    )
                    if s:
                        test.fail(
                            "Getting the empty list of xattr failed"
                            " on virtiofs fs, the output is %s" % o
                        )

                if winfsp_test_cmd:
                    # only for windows guest.
                    error_context.context(
                        "Run winfsp-tests suit on windows" " guest.", test.log.info
                    )
                    winfsp_copy_cmd = utils_misc.set_winutils_letter(
                        session, winfsp_copy_cmd
                    )
                    session.cmd(winfsp_copy_cmd)
                    try:
                        status, output = session.cmd_status_output(
                            winfsp_test_cmd % fs_dest, timeout=io_timeout
                        )
                        if status != 0:
                            test.fail("Winfsp-test failed, the output is %s" % output)
                    finally:
                        session.cmd("cd /d C:\\")

                if params.get("stop_start_repeats") and os_type == "windows":
                    viofs_sc_start_cmd = params["viofs_sc_start_cmd"]
                    viofs_sc_query_cmd = params["viofs_sc_query_cmd"]
                    viofs_sc_stop_cmd = params["viofs_sc_stop_cmd"]
                    repeats = int(params.get("stop_start_repeats", 1))
                    for i in range(repeats):
                        error_context.context(
                            "Repeat stop/start VirtioFsSvc:"
                            " %d/%d" % (i + 1, repeats),
                            test.log.info,
                        )
                        viofs_svc_stop_start("stop", viofs_sc_stop_cmd, "STOPPED")
                        viofs_svc_stop_start("start", viofs_sc_start_cmd, "RUNNING")
                    error_context.context(
                        "Basic IO test after" " repeat stop/start virtiofs" " service.",
                        test.log.info,
                    )
                    s, o = session.cmd_status_output(cmd_dd % guest_file, io_timeout)
                    if s:
                        test.fail("IO test failed, the output is %s" % o)

                if cmd_run_sesuit:
                    error_context.context(
                        "Run selinux_testsuits based on selinux label" "is enabled.",
                        test.log.info,
                    )
                    host_path = os.path.join(
                        data_dir.get_deps_dir("jfsutils"), jfsutils_pkg
                    )
                    scp_to_remote(
                        host_addr, port, username, password, host_path, "/tmp"
                    )
                    session.cmd(cmd_download_selinux_suits)
                    session.cmd(cmd_yum_install_se)
                    session.cmd(cmd_install_jfsutils)
                    status, output = session.cmd_status_output(
                        cmd_make_sesuit, timeout=timeout_make_sesuit
                    )
                    failed_make = output.split("Test Summary Report")[1]
                    # ignore the specific failed make files
                    ignore_make = re.findall(make_blacklist, failed_make).strip()
                    if ignore_make != make_blacklist:
                        test.fail(
                            "Make selinux testsuits failed, output is %s" % ignore_make
                        )
                    status, output = session.cmd_status_output(cmd_run_sesuit)
                    if status:
                        test.fail(
                            "Selinux-testsuits failed on virtiofs,"
                            " the output is %s" % output
                        )

                # during all virtio fs is mounted, reboot vm
                if params.get("reboot_guest", "no") == "yes":

                    def get_vfsd_num():
                        """
                        Get virtiofsd daemon number during vm boot up.
                        :return: virtiofsd daemon count.
                        """
                        cmd_ps_virtiofsd = params.get("cmd_ps_virtiofsd")
                        vfsd_num = 0
                        for device in vm.devices:
                            if isinstance(device, qdevices.QVirtioFSDev):
                                sock_path = device.get_param("sock_path")
                                cmd_ps_virtiofsd = cmd_ps_virtiofsd % sock_path
                                vfsd_ps = process.system_output(
                                    cmd_ps_virtiofsd, shell=True
                                )
                                vfsd_num += len(vfsd_ps.strip().splitlines())
                        return vfsd_num

                    reboot_method = params.get("reboot_method")

                    error_context.context(
                        "Check virtiofs daemon before reboot vm.", test.log.info
                    )
                    vfsd_num_bf = get_vfsd_num()

                    error_context.context(
                        "Reboot guest and check virtiofs daemon.", test.log.info
                    )
                    session = vm.reboot(session, reboot_method)
                    if not vm.is_alive():
                        test.fail("After rebooting vm quit unexpectedly.")
                    vfsd_num_af = get_vfsd_num()
                    if vfsd_num_bf != vfsd_num_af:
                        test.fail(
                            "Virtiofs daemon is different before "
                            "and after reboot.\n"
                            "Before reboot: %s\n"
                            "After reboot: %s\n",
                            (vfsd_num_bf, vfsd_num_af),
                        )
                    error_context.context(
                        "Start IO test on virtiofs after reboot vm.", test.log.info
                    )
                    if os_type == "windows":
                        virtio_fs_utils.start_viofs_service(test, params, session)
                    else:
                        error_context.context(
                            "Mount virtiofs target %s to %s inside"
                            "guest." % (fs_target, fs_dest),
                            test.log.info,
                        )
                        if not utils_disk.mount(
                            fs_target, fs_dest, "virtiofs", session=session
                        ):
                            test.fail("Mount virtiofs target failed.")
                    virtio_fs_utils.basic_io_test(test, params, session)
            finally:
                if os_type == "linux":
                    utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
                    utils_misc.safe_rmdir(fs_dest, session=session)
        # for multi fs test in windows guest, stop winfsp.launcher instance is needed.
        if params.get("viofs_svc_name") == "WinFSP.Launcher":
            error_context.context("Unmount fs with WinFsp.Launcher.z", test.log.info)
            instance_stop_cmd = params["instance_stop_cmd"]
            for fs in params.objects("filesystems"):
                fs_params = params.object_params(fs)
                fs_target = fs_params.get("fs_target")
                session.cmd(instance_stop_cmd % fs_target)
        # for windows guest, disable/uninstall driver to get memory leak based on
        # driver verifier is enabled
        if os_type == "windows":
            win_driver_utils.memory_leak_check(vm, test, params)
    finally:
        if os_type == "windows" and vm and vm.is_alive():
            virtio_fs_utils.delete_viofs_serivce(test, params, session)
            if params.get("reboot_after_delete_service", "no") == "yes":
                session = vm.reboot(session)
        if setup_local_nfs:
            if vm and vm.is_alive():
                vm.destroy()
            for fs in params.objects("filesystems"):
                nfs_local = nfs_local_dic[fs]
                nfs_local.cleanup()
        if setup_filesystem_on_host:
            cmd = "if losetup -l {0};then losetup -d {0};fi;".format(loop_device)
            cmd += "umount -l {0};".format(fs_source)
            process.system_output(cmd, shell=True, timeout=60)
            if utils_misc.check_exists(dd_of_on_host):
                cmd_del = "rm -rf " + dd_of_on_host
                process.run(cmd_del, timeout=60)
        if security_label_test:
            if se_mode_host_before != se_mode:
                try:
                    utils_selinux.set_status(se_mode_host_before)
                except Exception as err_msg:
                    test.fail(
                        "Restore selinux failed with %s on" "host." % str(err_msg)
                    )
            if os_type == "linux" and not se_mode_guest_before == se_mode:
                test.log.info(
                    "Need to change selinux mode back to" " %s.", se_mode_guest_before
                )
                if se_mode_guest_before.lower() == "disabled":
                    cmd = (
                        "sed -i 's/^SELINUX=.*/SELINUX=Disabled/g' /etc/selinux/config"
                    )
                    session.cmd(cmd)
                    session = vm.reboot(session)
                if se_mode_guest_before.lower() == "permissive":
                    session.cmd("setenforce Permissive")
