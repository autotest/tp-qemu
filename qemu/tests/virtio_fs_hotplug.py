import os
import shutil
import time

from avocado.utils import process
from virttest import data_dir, error_context, utils_disk, utils_misc, utils_test
from virttest.qemu_devices import qdevices
from virttest.utils_windows import virtio_win

from provider import win_driver_utils


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug/unplug virtiofs devices.
    Steps:
        1) Boot up guest with/without virtiofs device(s).
            a. start virtiofs daemon
            b. boot up guest
        2) Hoplug virtiofs device.
        3) Mount virtiofs.
        4) Do read/write data on hotplug fs.
        5) Unplug virtiofs device
        6) repeate step2-5
        7) hotplug multiple virtiofs device as step2-5

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

    def config_win_before_test(session):
        """
        Only for windows guest, enable driver verifier and install winscp.
        """
        error_context.context(
            "Do driver verify and winfsp installation" " in windows guest.",
            test.log.info,
        )
        check_installed_cmd = params["check_installed_cmd"] % install_path
        # Check whether windows driver is running,and enable driver verifier
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, driver_name
        )
        # install winfsp tool
        error_context.context("Install winfsp for windows guest.", test.log.info)
        installed = session.cmd_status(check_installed_cmd) == 0
        if installed:
            test.log.info("Winfsp tool is already installed.")
        else:
            install_cmd = utils_misc.set_winutils_letter(session, params["install_cmd"])
            session.cmd(install_cmd, 60)
            if not utils_misc.wait_for(
                lambda: not session.cmd_status(check_installed_cmd), 60
            ):
                test.error("Winfsp tool is not installed.")
        return session

    def mount_guest_fs(session):
        """
        Mount virtiofs on linux guest.
        """
        error_context.context(
            "Create a destination directory %s " "inside guest." % fs_dest,
            test.log.info,
        )
        utils_misc.make_dirs(fs_dest, session)
        error_context.context(
            "Mount virtiofs target %s to %s inside" " guest." % (fs_target, fs_dest),
            test.log.info,
        )
        if not utils_disk.mount(fs_target, fs_dest, "virtiofs", session=session):
            test.fail("Mount virtiofs target failed.")

    def start_vfs_service(session):
        """
        Start virtiofs service in windows guest
        """
        error_context.context("Start virtiofs service in windows guest.", test.log.info)
        test.log.info(
            "Check if virtiofs service is registered with %s.", viofs_sc_query_cmd
        )
        status, output = session.cmd_status_output(viofs_sc_query_cmd)
        if "not exist as an installed service" in output:
            test.log.info("Register virtiofs service in windows guest.")
            exe_path = get_viofs_exe(session)
            # copy virtiofs.exe to c: in case the virtio-win cdrom volume name
            # is changed in other cases of a loop.
            session.cmd(params.get("viofs_exe_copy_cmd") % exe_path)
            sc_create_s, sc_create_o = session.cmd_status_output(viofs_sc_create_cmd)
            if sc_create_s != 0:
                test.fail(
                    "Failed to register virtiofs service, output is %s" % sc_create_o
                )
        test.log.info("Check if virtiofs service is started.")
        status, output = session.cmd_status_output(viofs_sc_query_cmd)
        if "RUNNING" not in output:
            test.log.info("Start virtiofs service.")
            sc_start_s, sc_start_o = session.cmd_status_output(viofs_sc_start_cmd)
            if sc_start_s != 0:
                test.fail("Failed to start virtiofs service, output is %s" % sc_start_o)
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
                error_context.context("Configure virtiofs debug log.", test.log.info)
                for reg_cmd in (viofs_debug_enable_cmd, viofs_log_enable_cmd):
                    error_context.context("Set %s " % reg_cmd, test.log.info)
                    s, o = session.cmd_status_output(reg_cmd)
                    if s:
                        test.fail("Fail command: %s. Output: %s" % (reg_cmd, o))
                error_context.context("Reboot guest.", test.log.info)
                session = vm.reboot()
                # sleep a while after os reboot
                time.sleep(5)
            else:
                test.log.info("Virtiofs debug log is enabled.")
        return session

    def get_win_dst_dir(session):
        """
        get fs dest for windows vm.
        """
        virtio_fs_disk_label = fs_target
        error_context.context(
            "Get Volume letter of virtio fs target, the disk"
            "lable is %s." % virtio_fs_disk_label,
            test.log.info,
        )
        vol_con = "VolumeName='%s'" % virtio_fs_disk_label
        volume_letter = utils_misc.wait_for(
            lambda: utils_misc.get_win_disk_vol(session, condition=vol_con), 60
        )
        if volume_letter is None:
            test.fail("Could not get virtio-fs mounted volume letter.")
        return volume_letter, "%s:" % volume_letter

    def run_io_test(session, volume_letter, fs_dest):
        """
        Run io test on the shared dir.
        """
        error_context.context("Run io test on the %s." % fs_dest, test.log.info)
        guest_file = os.path.join(fs_dest, test_file)
        error_context.context(
            "Creating file under %s inside " "guest." % fs_dest, test.log.info
        )
        session.cmd(cmd_dd % guest_file, io_timeout)
        if os_type == "linux":
            cmd_md5_vm = cmd_md5 % guest_file
        else:
            guest_file_win = guest_file.replace("/", "\\")
            cmd_md5_vm = cmd_md5 % (volume_letter, guest_file_win)
        md5_guest = session.cmd_output(cmd_md5_vm, io_timeout).strip().split()[0]

        test.log.info(md5_guest)
        md5_host = (
            process.run("md5sum %s" % host_data, io_timeout)
            .stdout_text.strip()
            .split()[0]
        )
        if md5_guest != md5_host:
            test.fail("The md5 value of host is not the same with guest.")

        error_context.context("Unmount the point after finish io test", test.log.info)
        if os_type == "linux":
            utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
            utils_misc.safe_rmdir(fs_dest, session=session)

    def io_test_after_hotplug(session, fs_dest):
        """
        function test after virtiofs is hotplugged
        """
        volume_letter = None
        if os_type == "windows":
            session = config_win_before_test(session)
            session = start_vfs_service(session)
            volume_letter, fs_dest = get_win_dst_dir(session)
        else:
            mount_guest_fs(session)
        run_io_test(session, volume_letter, fs_dest)
        return session

    def create_fs_devices(fs_name, fs_params):
        """
        Create fs devices.
        """
        return vm.devices.fs_define_by_params(fs_name, fs_params)

    def get_fs_devices(fs_target):
        """
        Get fs devices from devices.
        """
        vufs_dev = vm.devices.get_by_params({"tag": fs_target})[0]
        char_dev_id = vufs_dev.get_param("chardev")
        char_dev = vm.devices.get(char_dev_id)
        char_dev.set_param("server", "off")
        sock_path = char_dev.get_param("path")
        vfsd_dev = vm.devices.get_by_params({"sock_path": sock_path})[0]
        return [vfsd_dev, char_dev, vufs_dev]

    def plug_fs_devices(action, plug_devices):
        """
        Plug/unplug fs devices.
        """
        plug_devices = plug_devices if action == "hotplug" else plug_devices[::-1]
        for dev in plug_devices:
            error_context.context(
                "%s %s device (iteration %d)"
                % (action.capitalize(), dev.get_qid(), iteration),
                test.log.info,
            )
            if isinstance(dev, qdevices.CharDevice):
                dev.set_param("server", "off")
            if isinstance(dev, qdevices.QDevice) and action == "hotplug":
                if (
                    "q35" in params["machine_type"]
                    or "arm64-pci" in params["machine_type"]
                ):
                    parent_bus = "pcie_extra_root_port_%s" % index
                elif "s390" in params["machine_type"]:
                    parent_bus = "virtual-css"
                else:
                    parent_bus = "pci.0"
                parent_bus_obj = vm.devices.get_buses({"aobject": parent_bus})[0]
                ret = getattr(vm.devices, "simple_%s" % action)(
                    dev, vm.monitor, bus=parent_bus_obj
                )
                if not ret[1]:
                    test.fail("Failed to hotplug '%s'" % dev)
                continue
            ret = getattr(vm.devices, "simple_%s" % action)(dev, vm.monitor)
            if not ret[1]:
                test.fail("Failed to hotplug '%s'" % dev)

    test_file = params.get("test_file")
    cmd_dd = params.get("cmd_dd")
    cmd_md5 = params.get("cmd_md5")
    io_timeout = params.get_numeric("io_timeout")
    install_path = params.get("install_path")
    need_plug = params.get("need_plug", "no") == "yes"

    # windows config
    viofs_sc_create_cmd = params.get("viofs_sc_create_cmd")
    viofs_sc_start_cmd = params.get("viofs_sc_start_cmd")
    viofs_sc_query_cmd = params.get("viofs_sc_query_cmd")
    driver_name = params.get("driver_name")

    os_type = params.get("os_type")
    vm = env.get_vm(params.get("main_vm"))
    vm.verify_alive()
    session = vm.wait_for_login()

    unplug_devs = []
    if need_plug:
        params["filesystems"] = params.get("extra_filesystems")
    try:
        for iteration in range(int(params.get("repeat_times", 3))):
            for index, fs in enumerate(params.objects("filesystems")):
                fs_params = params.object_params(fs)
                fs_target = fs_params.get("fs_target")
                fs_dest = fs_params.get("fs_dest")
                fs_source = fs_params.get("fs_source_dir")
                base_dir = fs_params.get("fs_source_base_dir", data_dir.get_data_dir())
                if not os.path.isabs(fs_source):
                    fs_source = os.path.join(base_dir, fs_source)
                host_data = os.path.join(fs_source, test_file)

                if need_plug:
                    if os.path.exists(fs_source):
                        shutil.rmtree(fs_source, ignore_errors=True)
                    test.log.info("Create filesystem source %s.", fs_source)
                    os.makedirs(fs_source)

                    fs_devs = create_fs_devices(fs, fs_params)
                    plug_fs_devices("hotplug", fs_devs)
                    session = io_test_after_hotplug(session, fs_dest)

                unplug_devs.extend(fs_devs if need_plug else get_fs_devices(fs_target))
            plug_fs_devices("unplug", unplug_devs)
            del unplug_devs[:]
        # for windows guest, disable/uninstall driver to get memory leak based on
        # driver verifier is enabled
        if os_type == "windows" and need_plug:
            plug_fs_devices("hotplug", fs_devs)
            win_driver_utils.memory_leak_check(vm, test, params)
    finally:
        if os_type == "linux":
            utils_disk.umount(fs_target, fs_dest, "virtiofs", session=session)
            utils_misc.safe_rmdir(fs_dest, session=session)
