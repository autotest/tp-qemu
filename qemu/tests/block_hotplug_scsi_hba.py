import re

from virttest import error_context, utils_misc
from virttest.utils_test import qemu

from provider import win_driver_utils
from provider.block_devices_plug import BlockDevicesPlug


@error_context.context_aware
def run(test, params, env):
    """
    Test the virtio scsi block device with virtio-scsi-pci.hotplug=on
    or off.
      Steps:
        1. Start VM with virtio-scsi-pci(system disk).
        2. Check whether vioscsi.sys verifier enabled in windows guest.
        3. Hotplug a virtio-scsi disk with virtio-scsi-pci.hotplug=off
           via qmp.
        4. Check the new disk in guest.
        5. Rescan the scsi bus in the guest and recheck the disk.
        6. Retest the step 3-4 with hotplug=on specified and then
           hot-unplug it.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def list_all_disks(session):
        """List all disks inside guest."""
        if is_linux:
            return utils_misc.list_linux_guest_disks(session)
        return set(session.cmd("wmic diskdrive get index").split()[1:])

    def _get_scsi_host_id(session):
        test.log.info("Get the scsi host id which is hot plugged.")
        output = session.cmd(
            'dmesg | grep "scsi host" | ' "awk 'END{print}' | awk '{print $4}'"
        )
        return re.search(r"(\d+)", output).group(1)

    def _rescan_hba_controller_linux(session):
        session.cmd(
            'echo "- - -" > /sys/class/scsi_host/host%s/scan'
            % _get_scsi_host_id(session)
        )

    def _rescan_hba_controller_windows(session):
        session.cmd(
            "echo rescan > {0} && echo exit >> {0} && diskpart / {0} "
            "&& del /f {0}".format("diskpart_script"),
            300,
        )

    def rescan_hba_controller(session):
        """Rescan the scsi hba controller."""
        error_context.context("Rescan the scsi hba controller.", test.log.info)
        if is_linux:
            _rescan_hba_controller_linux(session)
        else:
            _rescan_hba_controller_windows(session)

    is_linux = params["os_type"] == "linux"
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=360)

    if not is_linux:
        session = qemu.windrv_check_running_verifier(
            session, vm, test, params["driver_name"], 360
        )

    orig_disks = list_all_disks(session)
    plug = BlockDevicesPlug(vm)
    plug.hotplug_devs_serial(interval=int(params["hotplug_interval"]))
    if params["need_rescan_hba"] == "yes":
        if utils_misc.wait_for(
            lambda: bool(list_all_disks(session) - orig_disks), 30, step=3
        ):
            test.log.debug("The all disks: %s.", list_all_disks(session))
            test.fail(
                "Found a new disk with virtio-scsi-pci.hotplug=off "
                "before rescan scsi hba controller."
            )
        rescan_hba_controller(session)
    if not is_linux:
        win_driver_utils.memory_leak_check(vm, test, params)
    plug.unplug_devs_serial()
