import ast
import re

from virttest import error_context, utils_misc, utils_test

from provider.block_devices_plug import BlockDevicesPlug

HOTPLUG, UNPLUG = ("hotplug", "unplug")


@error_context.context_aware
def run(test, params, env):
    """
    Test plug cdrom device.
      Scenario "with_hotplug":
        1) Start VM with virtio-scsi-pci (system disk).
        2) For windows, Check whether vioscsi.sys verifier enabled in guest.
        3) Hot plug a virtio-scsi cdrom via qmp.
        4) Check in qmp monitor.
        5) Check in VM, the cdrom show in system computer.
        6) For linux, check guest kernel logs.
        7) Reboot then shutdown guest.

      Scenario "with_unplug":
        1) Boot a guest with virtio-scsi CD-ROM normally.
        2) Check block in QMP.
        3) Delete the virtio-scsi CD-ROM by qmp.
        4) Reboot then shutdown guest.

    :param test:   QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env:    Dictionary with test environment.
    """

    def _shutdown_vm(session):
        """Shutdown vm."""
        shutdown_command = params["shutdown_cmd"]
        error_context.context(
            'Shutting down VM by "%s".' % shutdown_command, test.log.info
        )
        session.sendline(shutdown_command)
        if not vm.wait_for_shutdown():
            test.fail("Failed to shutdown vm.")

    def _reboot_vm(session):
        """Reboot vm."""
        error_context.context("Rebooting VM.", test.log.info)
        return vm.reboot(session=session, timeout=360)

    def _check_cdrom_info_by_qmp(items):
        """Check the cdrom device info by qmp."""
        error_context.context(
            'Check if the info "%s" are match with the output of query-block.'
            % str(items),
            test.log.info,
        )
        blocks = vm.monitor.info_block()
        for key, val in items.items():
            if (key == "device" and val == dev_id) or blocks[dev_id][key] == val:
                continue
            test.fail('No such "%s: %s" in the output of query-block.' % (key, val))

    def _check_cdrom_info_by_guest():
        """Check cdrom info inside guest."""
        test.log.info('Check if the file "%s" is in the cdrom.', iso_name)
        cmd_map = {
            "linux": "mount /dev/sr{0} /mnt && ls /mnt && umount /mnt",
            "windows": "dir {0}:\\",
        }
        cd_exp_map = {"linux": r"sr([0-9])", "windows": r"(\w):"}
        get_cd_map = {
            "linux": "lsblk -nb",
            "windows": "wmic logicaldisk where (Description="
            "'CD-ROM Disc') get DeviceID",
        }
        letters = utils_misc.wait_for(
            lambda: re.findall(
                cd_exp_map[os_type], session.cmd(get_cd_map[os_type]), re.M
            ),
            3,
        )
        if not letters:
            test.error("No available CD-ROM devices")
        for index in range(len(cdroms)):
            if iso_name in session.cmd(cmd_map[os_type].format(letters[index])).lower():
                break
        else:
            test.fail('No such the file "%s" in cdrom.' % iso_name)

    def _check_cdrom_info(items):
        _check_cdrom_info_by_qmp(items)
        _check_cdrom_info_by_guest()

    os_type = params["os_type"]
    cdroms = params["cdroms"].split()
    is_windows = os_type == "windows"
    action = HOTPLUG if params.get("do_hotplug", "no") == "yes" else UNPLUG

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=360)

    if is_windows:
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, params["driver_name"], 300
        )

    plug = BlockDevicesPlug(vm)
    for cdrom in cdroms:
        cdrom_params = params.object_params(cdrom)
        if cdrom_params["cd_format"] == "ide":
            test.cancel("Hot-plug cd_format IDE not available, skipped")
        items_checked = ast.literal_eval(cdrom_params.get("items_checked"))
        dev_id = items_checked["device"]
        iso_name = cdrom_params.get("iso_name")
        if action == UNPLUG:
            _check_cdrom_info(items_checked)
        getattr(plug, "%s_devs_serial" % action)(cdrom)
        if action == HOTPLUG:
            _check_cdrom_info(items_checked)

    _shutdown_vm(_reboot_vm(session))
