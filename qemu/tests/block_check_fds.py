from avocado.utils import process
from virttest import error_context

from provider.block_devices_plug import BlockDevicesPlug


@error_context.context_aware
def run(test, params, env):
    """
    Test to check file descriptors when attaching and detaching
    virtio-scsi block devices.
    Steps:
        1. Boot a guest.
        2. Attach a block device then detach it and count AIO file
           descriptors.
        3. Run it many more times and notice the file descriptors
           creeping skyward or not.
        4. Run it 1000 times, the file descriptors is not increase.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def _get_aio_fds_num(pid):
        """Get the number of AIO file descriptors."""
        return int(process.system_output(lsof_cmd % pid, shell=True))

    def hotplug_unplug_block_repeatedly(times):
        """Hot plug then unplug block devices repeatedly."""
        vm_pid = vm.get_pid()
        plug = BlockDevicesPlug(vm)
        info = "The number of AIO file descriptors is %s " "after %s block device."
        for i in range(times):
            test.log.info("Iteration %d: Hot plug then unplug " "block device.", i)
            plug.hotplug_devs_serial()
            orig_fds_num = _get_aio_fds_num(vm_pid)
            test.log.info(info, orig_fds_num, "hot plugging")
            plug.unplug_devs_serial()
            new_fds_num = _get_aio_fds_num(vm_pid)
            test.log.info(info, new_fds_num, "unplugging")
            if new_fds_num != orig_fds_num:
                test.fail(
                    "The the number of AIO descriptors is "
                    "changed, from %s to %s." % (orig_fds_num, new_fds_num)
                )

    lsof_cmd = params["lsof_cmd"]
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    vm.wait_for_login()
    hotplug_unplug_block_repeatedly(int(params["repeat_times"]))
