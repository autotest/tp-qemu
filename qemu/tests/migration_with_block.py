import ast
import os
import re
import sys
import threading

import six
from avocado.utils import process
from virttest import data_dir, error_context, utils_disk, utils_misc, utils_test
from virttest.remote import scp_to_remote

from provider import win_driver_utils
from provider.cdrom import QMPEventCheckCDChange, QMPEventCheckCDEject
from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Test block devices with migration..

        Scenario "with_scsi_on2off":
            1) Boot guest with scsi=on on src host.
            2) Boot guest with scsi=off on dst host.
            3) Do live Migration.

        Scenario "with_change_cdrom":
            1) Run qemu with specified cdrom loaded.
            2) Check the cdrom info by qmp.
            3) Check the cdrom's size inside guest.
            4) Eject cdrom, and check the info again.
            5) Load a new cdrom image, and check the cdrom info again.
            6) Check the cdrom's size inside guest.
            7) Start dest vm with new iso file in listening mode.
            8) Migrate from src to dst.
            9) Do system_reset in dst vm.

        Scenario "with_dataplane_on2off":
            1) Start VM with dataplane (both system disk and data disk).
            2) For Windows: check whether viostor.sys verifier enabled in guest.
            3) Do live migration.
            4) Do iozone testing after migration.
            5) Reboot guest.

        Scenario "with_post_copy.with_mem_stress":
            1) Start source VM with virtio-scsi-pci (system and data disks)
            2) For Windows: check whether viostor.sys verifier enabled in guest.
            3) Run stress guest.
            4) Start dst guest with "-incoming tcp:x:xxxx"/
            5) On source qemu & dst qemu, set postcopy mode on.
            6) Do live migration.
            7) Migration could not finish under high stress,
               then change into postcopy mode.
            8) Repeat step 4~7 to migrate guest back to source host.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    class _StressThread(threading.Thread):
        def __init__(self, target, exit_event, args=()):
            threading.Thread.__init__(self)
            self.exc_info = None
            self.exit_event = exit_event
            self._target = target
            self._args = args

        def run(self):
            try:
                self._target(*self._args)
            except Exception as e:
                test.log.error(str(e))
                self.exc_info = sys.exc_info()
                self.exit_event.set()

    def scp_package(src, dst):
        """Copy file from the host to the guest."""
        scp_to_remote(
            vm.get_address(),
            "22",
            params.get("username"),
            params.get("password"),
            src,
            dst,
        )

    def unpack_package(session, src, dst):
        """Unpack the package."""
        session.cmd("tar -xvf %s -C %s" % (src, dst))

    def install_package(session, src, dst):
        """Install the package."""
        cmd = " && ".join(("cd %s && ./configure --prefix=%s", "make && make install"))
        session.cmd(cmd % (src, dst), 300)

    def cleanup(session, src):
        """Remove files."""
        session.cmd("rm -rf %s" % src)

    def _get_data_disks_linux():
        """Get the data disks by serial or wwn options in linux."""
        for data_image in params["images"].split()[1:]:
            extra_params = params.get("blk_extra_params_%s" % data_image, "")
            match = re.search(r"(serial|wwn)=(\w+)", extra_params, re.M)
            if match:
                drive_id = match.group(2)
            else:
                continue
            drive_path = utils_misc.get_linux_drive_path(session, drive_id)
            if not drive_path:
                test.error("Failed to get '%s' drive path" % data_image)
            yield drive_path[5:], params.object_params(data_image)["image_size"]

    def _get_data_disks_win():
        """Get the data disks in windows."""
        for data_image in params["images"].split()[1:]:
            size = params.object_params(data_image)["image_size"]
            yield utils_disk.get_windows_disks_index(session, size)[0], size

    def get_data_disks():
        """Get the data disks."""
        _get_disks = _get_data_disks_win if windows else _get_data_disks_linux
        for disk, size in _get_disks():
            yield disk, size

    def format_data_disks():
        """Format the data disks."""
        for disk, size in get_data_disks():
            if windows:
                if not utils_disk.update_windows_disk_attributes(session, disk):
                    test.fail("Failed to update windows disk attributes.")
            yield utils_disk.configure_empty_disk(session, disk, size, os_type)[0]

    def run_iozone(timeout):
        """Do iozone testing inside guest."""
        test.log.info("Do iozone testing on data disks.")
        iozone = generate_instance(params, vm, "iozone")
        try:
            for target in format_data_disks():
                iozone.run(stress_options.format(target), timeout)
        finally:
            iozone.clean()

    def run_stressapptest(timeout):
        """Do stressapptest testing inside guest."""
        test.log.info("Do stressapptest testing on data disks.")
        sub_session = vm.wait_for_login(timeout=360)
        try:
            host_path = os.path.join(
                data_dir.get_deps_dir("stress"), "stressapptest.tar"
            )
            scp_package(host_path, "/home/")
            unpack_package(sub_session, "/home/stressapptest.tar", "/home")
            install_package(sub_session, "/home/stressapptest", "/home/stressapptest")
            stress_bin_path = "/home/stressapptest/bin/stressapptest"
            sub_session.cmd("{} {}".format(stress_bin_path, stress_options), timeout)
        finally:
            cleanup(sub_session, "/home/stressapptest*")
            sub_session.close()

    def run_stress_background(timeout):
        """Run stress inside guest."""
        thread = _StressThread(stress_maps[stress_name], exit_event, (timeout,))
        thread.start()
        return thread

    def get_cdrom_size():
        """Get the size of cdrom device inside guest."""
        error_context.context("Get the cdrom's size in guest.", test.log.info)
        cmd = params["check_size"]
        if not utils_misc.wait_for(
            lambda: re.search(r"(\d+)", session.cmd(cmd), re.M), 10
        ):
            test.fail("Failed to get the cdrom's size.")
        cdrom_size = re.search(r"(\d+)", session.cmd(cmd), re.M).group(1)
        cdrom_size = int(cdrom_size) * 512 if not windows else int(cdrom_size)
        test.log.info("The cdrom's size is %s in guest.", cdrom_size)
        return cdrom_size

    def get_iso_size(iso_file):
        """Get the size of iso on host."""
        error_context.context("Get the iso size on host.", test.log.info)
        return int(
            process.system_output(
                "ls -l %s | awk '{print $5}'" % iso_file, shell=True
            ).decode()
        )

    def compare_cdrom_size(iso_file):
        """Compare the cdrom's size between host and guest."""
        error_context.context(
            "Compare the cdrom's size between host and guest.", test.log.info
        )
        ios_size = get_iso_size(iso_file)
        if not utils_misc.wait_for(lambda: get_cdrom_size() == ios_size, 30, step=3):
            test.fail("The size inside guest is not equal to iso size on host.")
        return get_cdrom_size()

    def check_cdrom_info_by_qmp(check_items):
        """Check the cdrom device info by qmp."""
        error_context.context(
            'Check if the info "%s" are match with the output of query-block.'
            % str(check_items),
            test.log.info,
        )
        blocks = vm.monitor.info_block()
        for key, val in check_items.items():
            if blocks[device_name][key] == val:  # pylint: disable=E0606
                continue
            test.fail('No such "%s: %s" in the output of query-block.' % (key, val))

    def check_block(block):
        """Check if the block device is existed in query-block."""
        return True if block in str(vm.monitor.info("block")) else False

    def eject_cdrom():
        """Eject cdrom."""
        error_context.context("Eject the original device.", test.log.info)
        with eject_check:  # pylint: disable=E0606
            vm.eject_cdrom(device_name, True)
        if check_block(orig_img_name):  # pylint: disable=E0606
            test.fail("Failed to eject cdrom %s. " % orig_img_name)

    def change_cdrom():
        """Change cdrom."""
        error_context.context("Insert new image to device.", test.log.info)
        with change_check:  # pylint: disable=E0606
            vm.change_media(device_name, new_img_name)  # pylint: disable=E0606
        if not check_block(new_img_name):
            test.fail("Fail to change cdrom to %s." % new_img_name)

    def change_vm_power():
        """Change the vm power."""
        method, command = params["command_opts"].split(",")
        test.log.info("Sending command(%s): %s", method, command)
        if method == "shell":
            p_session = vm.wait_for_login(timeout=360)
            p_session.sendline(command)
            p_session.close()
        else:
            getattr(vm.monitor, command)()

    def check_vm_status(timeout=600):
        """Check the status of vm."""
        action = "shutdown" if shutdown_vm else "login"
        if not getattr(vm, "wait_for_%s" % action)(timeout=timeout):
            test.fail("Failed to %s vm." % action)

    def set_dst_params():
        """Set the params of dst vm."""
        for name, val in ast.literal_eval(params.get("set_dst_params", "{}")).items():
            vm.params[name] = val

    def ping_pong_migration(repeat_times):
        """Do ping pong migration."""
        for i in range(repeat_times):
            set_dst_params()
            if i % 2 == 0:
                test.log.info("Round %s ping...", str(i / 2))
            else:
                test.log.info("Round %s pong...", str(i / 2))
            if do_migration_background:
                args = (mig_timeout, mig_protocol, mig_cancel_delay)
                kwargs = {
                    "migrate_capabilities": capabilities,
                    "mig_inner_funcs": inner_funcs,
                    "env": env,
                }
                migration_thread = utils_misc.InterruptedThread(
                    vm.migrate, args, kwargs
                )
                migration_thread.start()
                if not utils_misc.wait_for(
                    lambda: (
                        bool(vm.monitor.query("migrate"))
                        and ("completed" != vm.monitor.query("migrate")["status"])
                    ),
                    timeout=60,
                    first=10,
                ):
                    test.error("Migration thread is not alive.")
                vm.monitor.wait_for_migrate_progress(
                    float(params["percent_start_post_copy"])
                )
                vm.monitor.migrate_start_postcopy()
                migration_thread.join()
                test.log.info("Migration thread is done.")
            else:
                vm.migrate(
                    mig_timeout,
                    mig_protocol,
                    mig_cancel_delay,
                    migrate_capabilities=capabilities,
                    mig_inner_funcs=inner_funcs,
                    env=env,
                )

    def bg_stress_is_alive(session, name):
        """Check whether the background stress is alive."""
        return session.cmd_output("pgrep -xl %s" % name)

    shutdown_vm = params.get("shutdown_vm", "no") == "yes"
    reboot = params.get("reboot_vm", "no") == "yes"
    with_cdrom = params.get("with_cdrom", "no") == "yes"
    os_type = params["os_type"]
    windows = os_type == "windows"
    src_desc = params.get("src_addition_desc", "")
    dst_desc = params.get("dst_addition_desc", "")

    mig_timeout = float(params.get("mig_timeout", "3600"))
    mig_protocol = params.get("migration_protocol", "tcp")
    mig_cancel_delay = int(params.get("mig_cancel") == "yes") * 2
    inner_funcs = ast.literal_eval(params.get("migrate_inner_funcs", "[]"))
    capabilities = ast.literal_eval(params.get("migrate_capabilities", "{}"))
    do_migration_background = params.get("do_migration_background", "no") == "yes"

    stress_name = params.get("stress_name")
    stress_maps = {"iozone": run_iozone, "stressapptest": run_stressapptest}
    stress_options = params.get("stress_options")
    stress_timeout = int(params.get("stress_timeout", "1800"))
    do_stress_background = params.get("do_stress_background", "no") == "yes"
    kill_bg_stress = params.get("kill_bg_stress", "no") == "yes"

    exit_event = threading.Event()

    error_context.context("Boot guest %s on src host." % src_desc, test.log.info)
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=360)
    if windows:
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, params["driver_name"]
        )

    if params.get("run_stress_before_migration", "no") == "yes":
        if do_stress_background:
            stress_thread = run_stress_background(stress_timeout)
            if not utils_misc.wait_for(
                lambda: (
                    stress_thread.exit_event.is_set()
                    or bg_stress_is_alive(session, stress_name)
                ),
                120,
                step=3,
            ):
                test.error("The %s is not alive." % stress_name)
            if stress_thread.exit_event.is_set():
                stress_thread.exit_event.clear()
                six.reraise(
                    stress_thread.exc_info[0],
                    stress_thread.exc_info[1],
                    stress_thread.exc_info[2],
                )
        else:
            stress_maps[stress_name](stress_timeout)

    if with_cdrom:
        cdrom_params = params.object_params(params["cdroms"])
        check_orig_items = ast.literal_eval(cdrom_params["check_orig_items"])
        orig_img_name = params["cdrom_orig_file"]
        new_img_name = params["cdrom_new_file"]
        device_name = vm.get_block({"file": orig_img_name})
        if device_name is None:
            test.fail("Failed to get device using image %s." % orig_img_name)
        check_cdrom_info_by_qmp(check_orig_items)
        orig_size = compare_cdrom_size(orig_img_name)

        eject_check = QMPEventCheckCDEject(vm, device_name)
        change_check = QMPEventCheckCDChange(vm, device_name)
        eject_cdrom()
        change_cdrom()

        device_name = vm.get_block({"file": new_img_name})
        check_new_items = ast.literal_eval(cdrom_params["check_new_items"])
        check_cdrom_info_by_qmp(check_new_items)
        new_size = compare_cdrom_size(new_img_name)
        if new_size == orig_size:
            test.fail("The new size inside guest is equal to the orig iso size.")

    error_context.context("Boot guest %s on dst host." % dst_desc, test.log.info)
    ping_pong_migration(int(params.get("repeat_ping_pong", "1")))

    if params.get("run_stress_after_migration", "no") == "yes":
        if do_stress_background:
            run_stress_background(stress_timeout)
        else:
            stress_maps[stress_name](stress_timeout)

    if do_stress_background:
        if bg_stress_is_alive(session, stress_name):
            if kill_bg_stress:
                session.cmd("killall %s" % stress_name)
            else:
                stress_thread.join(stress_timeout)
                if stress_thread.exit_event.is_set():
                    stress_thread.exit_event.clear()
                    six.reraise(
                        stress_thread.exc_info[0],
                        stress_thread.exc_info[1],
                        stress_thread.exc_info[2],
                    )

    if shutdown_vm or reboot:
        change_vm_power()
        check_vm_status()
    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if windows:
        if params.get("memory_leak_check", "no") == "yes":
            win_driver_utils.memory_leak_check(vm, test, params)
