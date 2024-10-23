import re
import time

from virttest import error_context, utils_disk, utils_misc, utils_test

from provider import win_driver_utils
from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Test block devices during io.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

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

    def configure_data_disks():
        """Configure the data disks."""
        if windows:
            utils_disk.update_windows_disk_attributes(
                session, (disk for disk, _ in get_data_disks())
            )
        return [
            utils_disk.configure_empty_disk(session, disk, size, os_type)[0]
            for disk, size in get_data_disks()
        ]

    def get_win_drive_letters_after_reboot():
        """Get the drive letters after reboot in windows."""
        new_mount_points = utils_misc.get_windows_drive_letters(
            vm.wait_for_login(timeout=362)
        )
        for mount_point in fixed_mount_points:  # pylint: disable=E0606
            new_mount_points.remove(mount_point)
        diff_num = len(orig_mount_points) - len(new_mount_points)
        if diff_num != 0:
            test.error(
                "No found the corresponding drive letters " "in %s disks." % diff_num
            )
        return new_mount_points

    def run_iozone(mount_points):
        """Run iozone inside guest."""
        iozone = generate_instance(params, vm, "iozone")
        try:
            for mount_point in mount_points:
                iozone.run(
                    params["iozone_cmd_opitons"] % mount_point,
                    int(params["iozone_timeout"]),
                )
        finally:
            iozone.clean()

    def run_stress(name, mount_points):
        """Run the stress inside guest."""
        run_stress_maps[name](mount_points)

    def is_stress_alive(session, name):
        """Check whether the stress is alive."""
        name = name.upper() + ".EXE" if windows else name
        chk_cmd = 'TASKLIST /FI "IMAGENAME eq %s' if windows else "pgrep -xl %s"
        return re.search(name, session.cmd_output(chk_cmd % name), re.I | re.M)

    def _change_vm_power():
        """Change the vm power."""
        method, command = params["command_opts"].split(",")
        test.log.info("Sending command(%s): %s", method, command)
        if method == "shell":
            power_session = vm.wait_for_login(timeout=360)
            power_session.sendline(command)
        else:
            getattr(vm.monitor, command)()
        if shutdown_vm:
            if not utils_misc.wait_for(lambda: vm.monitor.get_event("SHUTDOWN"), 600):
                raise test.fail("Not received SHUTDOWN QMP event.")

    def _check_vm_status():
        """Check the status of vm."""
        action = "shutdown" if shutdown_vm else "login"
        if not getattr(vm, "wait_for_%s" % action)(timeout=362):
            test.fail("Failed to %s vm." % action)
        test.log.info("%s vm successfully.", action.capitalize())

    def run_power_management_test():
        """Run power management test inside guest."""
        _change_vm_power()
        _check_vm_status()

    def run_bg_test(target, args=(), kwargs={}):
        """Run the test background."""
        error_context.context(target.__doc__, test.log.info)
        thread = utils_misc.InterruptedThread(target, args, kwargs)
        thread.daemon = True
        thread.start()
        return thread

    shutdown_vm = params.get("shutdown_vm", "no") == "yes"
    reboot = params.get("reboot_vm", "no") == "yes"

    with_data_disks = params.get("with_data_disks", "yes") == "yes"
    stress_name = params["stress_name"]
    run_stress_maps = {"iozone": run_iozone}
    stress_thread_timeout = int(params.get("stress_thread_timeout", 60))
    bg_test_thread_timeout = int(params.get("bg_test_thread_timeout", 600))
    sleep_time = int(params.get("sleep_time", 30))
    os_type = params["os_type"]
    windows = os_type == "windows"

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=360)

    if windows:
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, params["driver_name"]
        )

    if with_data_disks:
        orig_mount_points = configure_data_disks()
        fixed_mount_points = set(utils_misc.get_windows_drive_letters(session)) ^ set(
            orig_mount_points
        )
    else:
        orig_mount_points = ["C"] if windows else ["/home"]
    mount_points = orig_mount_points
    stress_thread = run_bg_test(run_stress, (stress_name, mount_points))

    if not utils_misc.wait_for(
        lambda: is_stress_alive(session, stress_name), 60, step=3.0
    ):
        test.error("The %s stress is not alive." % stress_name)
    time.sleep(sleep_time)
    if not is_stress_alive(session, stress_name):
        test.error("The %s stress is not alive after %s." % (stress_name, sleep_time))

    if shutdown_vm or reboot:
        bg_test_target = run_power_management_test
        bg_test_thread = run_bg_test(bg_test_target)
        bg_test_thread.join(bg_test_thread_timeout)

    if not shutdown_vm:
        stress_thread.join(stress_thread_timeout, True)
        if with_data_disks and windows:
            # XXX: The data disk letters will be changed after system reset in windows.
            mount_points = get_win_drive_letters_after_reboot()
        run_stress(stress_name, mount_points)
    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if windows:
        if params.get("memory_leak_check", "no") == "yes":
            win_driver_utils.memory_leak_check(vm, test, params)
