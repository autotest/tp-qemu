import logging

from virttest import data_dir, error_context
from virttest.vt_vmm.api import vmm
from virttest.vt_vmm.utils.instance_spec import qemu_spec

LOG = logging.getLogger("avocado." + __name__)


@error_context.context_aware
def run(test, params, env):
    """
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def block_hotplug(vm, image_name):
        """
        Hotplug disks and verify it in qtree.

        :param image_name: Image name of hotplug disk
        :return: List of objects for hotplug disk.
        """
        LOG.info("Hotplug the image: %s", image_name)
        vm_params = vm.params
        node = vmm.get_instance_node(vm.instance_id)
        disk_spec = qemu_spec.define_disk_device_spec(
            vm.name, vm_params, node.tag, image_name
        )
        vmm.attach_instance_device(vm.instance_id, disk_spec)
        blocks_info = vm.monitor.info("block")
        LOG.info("After hotplug block, the qmp info of %s: %s", vm.name, blocks_info)
        blk_info = session.cmd_output("lsblk")
        LOG.info("After hotplug block, the block info of %s: %s", vm.name, blk_info)

    def block_unplug(vm, image_name):
        """
        Hotplug disks and verify it in qtree.

        :param image_name: Image name of hotplug disk
        :return: List of objects for hotplug disk.
        """
        LOG.info("Unplug the image: %s", image_name)
        vm_params = vm.params
        node = vmm.get_instance_node(vm.instance_id)
        disk_spec = qemu_spec.define_disk_device_spec(
            vm.name, vm_params, node.tag, image_name
        )
        vmm.detach_instance_device(vm.instance_id, disk_spec)
        blocks_info = vm.monitor.info("block")
        LOG.info("After unplug block, the qmp info of %s: %s", vm.name, blocks_info)
        blk_info = session.cmd_output("lsblk")
        LOG.info("After unplug block, the block info of %s: %s", vm.name, blk_info)

    timeout = float(params.get("login_timeout", 240))
    vms = env.get_all_vms()
    for vm in vms:
        error_context.context("Try to log into guest '%s'." % vm.name, test.log.info)
        session = vm.wait_for_login(timeout=timeout, status_check=False)
        vm_ver = session.cmd_output("cat /proc/version")
        LOG.info("Version of %s: %s", vm.name, vm_ver)
        cpus_info = vm.monitor.info("cpus", debug=False)
        LOG.info("CPU info of %s: %s", vm.name, cpus_info)
        blocks_info = vm.monitor.info("block")
        LOG.info("Block info of %s: %s", vm.name, blocks_info)

        hotplug_images = params.get("hotplug_images")
        if hotplug_images:
            for img in hotplug_images.split():
                block_hotplug(vm, img)

        unplug_images = params.get("unplug_images")
        if unplug_images:
            for img in unplug_images.split():
                block_unplug(vm, img)

        if params.get("reboot") == "yes":
            reboot_method = params.get("reboot_method", "shell")
            session = vm.reboot(session, reboot_method, 0, timeout, True)
            vm_info = session.cmd_output("uname -a")
            LOG.info("Info %s: %s", vm.name, vm_info)
            blocks_info = vm.monitor.info("block")
            LOG.info("Block info of %s: %s", vm.name, blocks_info)
            vm.pause()
            vm.resume()
            session.close()

    for vm in vms:
        vm_params = params.object_params(vm.name)
        src_node = vm_params.get("vm_node")
        dst_node = vm_params.get("mig_dest_node")
        if dst_node:
            error_context.context(
                f"Migrating the guest {vm.name} from {src_node} to {dst_node}",
                test.log.info,
            )
            vm.migrate(
                timeout=3600,
                protocol="tcp",
                cancel_delay=None,
                offline=False,
                stable_check=False,
                clean=True,
                save_path=data_dir.get_tmp_dir(),
                dest_host=dst_node,
                remote_port=None,
                not_wait_for_migration=False,
                fd_src=None,
                fd_dst=None,
                migration_exec_cmd_src=None,
                migration_exec_cmd_dst=None,
                env=None,
                migrate_capabilities=None,
                mig_inner_funcs=None,
                migrate_parameters=(None, None),
            )

            error_context.context(
                "Try to log into guest '%s'." % vm.name, test.log.info
            )
            session = vm.wait_for_login(timeout=timeout)
            vm_ver = session.cmd_output("cat /proc/version")
            LOG.info("Version of %s: %s", vm.name, vm_ver)

            cpus_info = vm.monitor.info("cpus", debug=False)
            LOG.info("CPU info of %s: %s", vm.name, cpus_info)
