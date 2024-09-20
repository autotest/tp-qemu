import re
import time

from virttest import error_context, utils_disk, utils_misc

from provider.block_devices_plug import BlockDevicesPlug
from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Test hotplug of block devices.

    1) Boot up a guest with a system disk and a data disk.
    2) Do IO stress test on data disk.
    3) Unplug data disk during io stress.
    4) Reboot guest.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def _check_stress_status():
        """Check the status of stress."""
        ck_session = vm.wait_for_login(timeout=360)
        proc_name = check_cmd[os_type].split()[-1]
        cmd = check_cmd[os_type]
        if not utils_misc.wait_for(
            lambda: proc_name.lower() in ck_session.cmd_output(cmd).lower(),
            180,
            step=3.0,
        ):
            test.fail("%s is not alive!" % proc_name)
        ck_session.close()

    def _get_data_disk():
        """Get the data disk."""
        extra_params = params["blk_extra_params_%s" % params["images"].split()[-1]]
        if windows:
            return sorted(session.cmd("wmic diskdrive get index").split()[1:])[-1]
        drive_id = re.search(r"(serial|wwn)=(\w+)", extra_params, re.M).group(2)
        return utils_misc.get_linux_drive_path(session, drive_id)

    def _run_stress_background():
        """Run stress under background."""
        test.log.info("Start io stress under background.")
        thread = utils_misc.InterruptedThread(
            target[os_type]["name"], (target[os_type]["args"],)
        )
        thread.start()
        _check_stress_status()
        return thread

    check_cmd = {
        "linux": "pgrep -lx dd",
        "windows": 'TASKLIST /FI "IMAGENAME eq IOZONE.EXE',
    }
    os_type = params["os_type"]
    args = params["stress_args"]
    windows = os_type == "windows"
    target = {}
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    session = vm.wait_for_login(timeout=360)
    disk = _get_data_disk()
    if windows:
        iozone = generate_instance(params, vm, "iozone")
        utils_disk.update_windows_disk_attributes(session, disk)
        disk_letter = utils_disk.configure_empty_disk(
            session, disk, params["image_size_stg0"], os_type
        )[0]
        target[os_type] = {"name": iozone.run, "args": args.format(disk_letter)}
    else:
        target[os_type] = {"name": session.cmd, "args": args.format(disk)}

    stress_thread = _run_stress_background()
    time.sleep(float(params["sleep_time"]))
    _check_stress_status()
    BlockDevicesPlug(vm).unplug_devs_serial()
    stress_thread.join(suppress_exception=True)
    session.close()
    vm.monitor.system_reset()
    test.log.info("Login guest after reboot.")
    session = vm.wait_for_login(timeout=360)
