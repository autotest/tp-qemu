"""
hot-plug discard disk testing
"""

from avocado.utils import process
from virttest import data_dir, error_context, storage

from provider.block_devices_plug import BlockDevicesPlug


@error_context.context_aware
def run(test, params, env):
    """
    Qemu discard hotplug support test:

    1) Boot vm
    2) Hot-plug the data disk with discard option
    3) Format the data disk and mount it in guest
    4) Execute dd command to the mounted disk in guest
    5) Check disk size allocation
    6) Execute rm and fstrim command in guest
    7) Check disk size allocation
    8) Hot-unplug the data disk
    9) Reboot vm


    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_scsi_debug_disk():
        """ "
        Get scsi debug disk on host which created as scsi-block.
        """
        cmd = "lsblk -S -n -p|grep scsi_debug"
        status, output = process.getstatusoutput(cmd)

        if status != 0:
            test.fail("Can not find scsi_debug disk")

        return output.split()[0]

    def check_disk_allocation():
        """
        Get the disk size allocation
        """
        if scsi_debug == "yes":
            cmd = "cat /sys/bus/pseudo/drivers/scsi_debug/map"
            output = process.system_output(cmd).decode().split(",")
            return sum([abs(eval(i)) for i in output if i != ""])

        cmd = "stat -c %b " + disk_name
        return int(process.system_output(cmd).decode())

    vm_name = params["main_vm"]
    scsi_debug = params.get("scsi_debug", "no")
    data_tag = params["data_tag"]

    vm = env.get_vm(vm_name)
    vm.verify_alive()

    if scsi_debug == "yes":
        disk_name = get_scsi_debug_disk()
        vm.params["image_name_%s" % data_tag] = disk_name
    else:
        image_params = params.object_params(data_tag)
        disk_name = storage.get_image_filename(image_params, data_dir.get_data_dir())

    timeout = float(params.get("login_timeout", 240))
    session = vm.wait_for_login(timeout=timeout)
    plug = BlockDevicesPlug(vm)
    error_context.context("Hot-plug discarded disk in guest.", test.log.info)
    plug.hotplug_devs_serial(data_tag)
    guest_disk_name = "/dev/" + plug[0]

    guest_format_command = params["guest_format_command"].format(guest_disk_name)
    guest_dd_command = params["guest_dd_command"]
    guest_rm_command = params["guest_rm_command"]

    error_context.context("Format disk in guest.", test.log.info)
    session.cmd(guest_format_command)

    error_context.context("Fill data disk in guest.", test.log.info)
    session.cmd(guest_dd_command, ignore_all_errors=True)

    old_count = check_disk_allocation()
    error_context.context("Blocks before trim: %d" % old_count, test.log.info)

    error_context.context("Remove data from disk in guest.", test.log.info)
    session.cmd(guest_rm_command)

    guest_fstrim_command = params["guest_fstrim_command"]
    session.cmd(guest_fstrim_command)
    new_count = check_disk_allocation()
    error_context.context("Blocks after trim: %d" % new_count, test.log.info)
    if new_count >= old_count:
        test.fail("Unexpected fstrim result")

    error_context.context("Hot-unplug discarded disk in guest.", test.log.info)
    plug.unplug_devs_serial(data_tag)

    error_context.context("Reboot guest.", test.log.info)
    vm.reboot()
    vm.wait_for_login(timeout=timeout)
