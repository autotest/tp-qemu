from avocado.utils import process
from virttest import error_context, utils_disk, utils_test

from provider.block_devices_plug import BlockDevicesPlug
from provider.storage_benchmark import generate_instance


@error_context.context_aware
def run(test, params, env):
    """
    Hotplug/unplug passthrough disk test:
    1) Create passthrough disk with scsi_debug tool.
    2) Start the guest.
    3) Hotplug this passthrough disk.
    4) Create partition on this disk and format it.
    5) Do iozone/dd test on this disk.
    6) Reboot the guest.
    7) Unplug this passthrough disk.

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def create_path_disk():
        """Create a passthrough disk with scsi_debug"""
        process.getoutput(params["pre_command"], shell=True)
        disks_old = process.getoutput("ls -1d /dev/sd*", shell=True).split()
        process.system_output(
            params["create_command"], timeout=300, shell=True, verbose=False
        )
        disks_new = process.getoutput("ls -1d /dev/sd*", shell=True).split()
        return list(set(disks_new) - set(disks_old))[0]

    def hotplug_path_disk(vm, path_dev):
        """Hotplug passthrough disk."""
        error_context.context("Hotplug passthrough device", test.log.info)
        vm.params["image_name_stg0"] = path_dev
        plug = BlockDevicesPlug(vm)
        plug.hotplug_devs_serial()
        return plug[0]

    def format_plug_disk(session, did):
        """Format new hotpluged disk."""
        stg_image_size = params["stg_image_size"]
        ostype = params["os_type"]
        if ostype == "windows":
            if not utils_disk.update_windows_disk_attributes(session, did):
                test.fail(
                    "Failed to clear readonly for all disks and online " "them in guest"
                )
        partition = utils_disk.configure_empty_disk(
            session, did, stg_image_size, ostype
        )
        if not partition:
            test.fail("Fail to format disks.")
        return partition[0]

    def run_io_test(session, partition):
        """Run io test on the hot plugged disk."""
        iozone_options = params.get("iozone_options")
        dd_test = params.get("dd_test")
        if iozone_options:
            error_context.context("Run iozone test on the plugged disk.", test.log.info)
            iozone = generate_instance(params, vm, "iozone")
            iozone.run(iozone_options.format(partition[0]))
        if dd_test:
            error_context.context("Do dd test on the plugged disk", test.log.info)
            partition = partition.split("/")[-1]
            session.cmd(dd_test.format(partition))

    def unplug_path_disk(vm):
        """Unplug passthrough disk."""
        error_context.context("Unplug passthrouth device", test.log.info)
        plug = BlockDevicesPlug(vm)
        plug.unplug_devs_serial()

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login()

    if params["os_type"] == "windows":
        session = utils_test.qemu.windrv_check_running_verifier(
            session, vm, test, params["driver_name"]
        )

    drive_index = hotplug_path_disk(vm, create_path_disk())
    run_io_test(session, format_plug_disk(session, drive_index))
    session = vm.reboot(session)
    unplug_path_disk(vm)
    session.close()
