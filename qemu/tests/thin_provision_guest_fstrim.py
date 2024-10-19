from avocado.utils import path as utils_path
from avocado.utils import process
from virttest import env_process, error_context, guest_agent
from virttest.utils_misc import get_linux_drive_path


@error_context.context_aware
def run(test, params, env):
    """
    Execute guest-fstrim command to guest agent for discard testing:
    1) Load scsi_debug module on host.
    2) Boot guest with the scsi_debug emulated disk as data disk.
    3) Format data disk with ext4 or xfs in guest.
    4) Check the number blocks of the scsi_debug device.
    5) Mount the disk in guest then fill data on it.
    6) Check the number blocks of the scsi_debug device.
    7) Remove data from the data disk in guest.
    8) Execute guest-fstrim command to guest agent.
    9) Check the number blocks of the scsi_debug device. it should less than
       the number before execute guest-fstrim.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_scsi_debug_disk(guest_session=None):
        """ "
        Get scsi debug disk on host or on guest which created as scsi-block.
        """
        cmd = "lsblk -S -n -p|grep scsi_debug"

        if guest_session:
            status, output = guest_session.cmd_status_output(cmd)
        else:
            status, output = process.getstatusoutput(cmd)

        if status != 0:
            test.fail("Can not find scsi_debug disk")

        return output.split()[0]

    def get_guest_discard_disk():
        """
        Get discard disk on guest.
        """
        if params["drive_format_%s" % data_tag] == "scsi-block":
            return get_scsi_debug_disk(session)

        disk_serial = params["disk_serial"]
        return get_linux_drive_path(session, disk_serial)

    def create_guest_agent_session():
        """
        Create guest agent session.
        """
        guest_agent_serial_type = params["guest_agent_serial_type"]
        guest_agent_name = params["guest_agent_name"]
        filename = vm.get_serial_console_filename(guest_agent_name)
        guest_agent_params = params.object_params(guest_agent_name)
        guest_agent_params["monitor_filename"] = filename
        return guest_agent.QemuAgent(
            vm,
            guest_agent_name,
            guest_agent_serial_type,
            guest_agent_params,
            get_supported_cmds=True,
        )

    def get_blocks():
        """
        Get numbers blocks of the scsi debug disk on host.
        """
        cmd = "cat /sys/bus/pseudo/drivers/scsi_debug/map"
        output = process.system_output(cmd).decode().split(",")
        return sum([abs(eval(i)) for i in output if i != ""])

    utils_path.find_command("lsblk")
    disk_name = get_scsi_debug_disk()

    # prepare params to boot vm with scsi_debug disk.
    vm_name = params["main_vm"]
    data_tag = params["data_tag"]
    params["start_vm"] = "yes"
    params["image_name_%s" % data_tag] = disk_name

    error_context.context("Boot guest with disk '%s'" % disk_name, test.log.info)
    # boot guest with scsi_debug disk
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.verify_alive()
    session = vm.wait_for_login()

    agent_session = create_guest_agent_session()

    disk_name = get_guest_discard_disk()

    guest_format_command = params["guest_format_command"].format(disk_name)
    guest_dd_command = params["guest_dd_command"]
    guest_rm_command = params["guest_rm_command"]

    error_context.context("Format disk in guest.", test.log.info)
    session.cmd(guest_format_command)
    count = get_blocks()
    test.log.info("The initial blocks is %d", count)

    error_context.context("Fill data disk in guest.", test.log.info)
    session.cmd(guest_dd_command, ignore_all_errors=True)
    old_count = get_blocks()
    error_context.context("Blocks before trim: %d" % old_count, test.log.info)

    error_context.context("Remove data from disk in guest.", test.log.info)
    session.cmd(guest_rm_command)

    session.cmd("setenforce 0")
    error_context.context("Execute guest-fstrim command.", test.log.info)
    agent_session.fstrim()
    new_count = get_blocks()
    error_context.context("Blocks after trim: %d" % new_count, test.log.info)

    error_context.context("Compare blocks.", test.log.info)
    if new_count >= old_count:
        test.fail("Got unexpected result:%s %s" % (old_count, new_count))
