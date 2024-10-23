from virttest import env_process, utils_misc
from virttest.qemu_capabilities import Flags


def run(test, params, env):
    """
    Steps:
      1. Boot guest with scsi-cd without file, not dummy image.
      2. Add drive layer and insert media.

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def move_tary(action, dev_id):
        getattr(vm.monitor, "blockdev_%s_tray" % action)(dev_id)
        if not utils_misc.wait_for(
            lambda: vm.monitor.get_event(tray_move_event), 60, 0, 3
        ):
            test.fail(
                "Failed to get event %s after %s tray." % (tray_move_event, action)
            )

    tray_move_event = params.get("tray_move_event")
    dev_id = params.get("cdroms").split()[0]
    params["start_vm"] = "yes"
    vm_name = params.get("main_vm")
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)

    if not vm.check_capability(Flags.BLOCKDEV):
        test.cancel("Unsupported the insertion media.")
    vm.verify_alive()

    drive = vm.devices[dev_id]
    top_node = vm.devices[drive.get_param("drive")]
    nodes = [top_node]
    nodes.extend((n for n in top_node.get_child_nodes()))
    for node in nodes:
        vm.devices.remove(node, True)
        if node is not top_node:
            top_node.del_child_node(node)
    drive.set_param("drive", None)

    vm.destroy(False)
    vm = vm.clone(copy_state=True)
    vm.create()

    move_tary("open", dev_id)
    vm.monitor.blockdev_remove_medium(dev_id)
    for node in reversed(nodes):
        vm.devices.simple_hotplug(node, vm.monitor)
    vm.monitor.blockdev_insert_medium(dev_id, top_node.get_qid())
    move_tary("close", dev_id)
    vm.destroy()
