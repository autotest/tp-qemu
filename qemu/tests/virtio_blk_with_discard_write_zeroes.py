import ast
import re

from virttest import env_process, error_context, qemu_qtree, utils_misc, virt_vm


@error_context.context_aware
def run(test, params, env):
    """
    Test virtio_blk with options "discard" and "write_zeroes".
    Steps:
        1. Boot up a virtio-blk guest with options 'discard' and
           'write_zeroes' enabled or disabled.
        2. Check if discard and write-zeroes attribute works.
        3. In guest, check if discard enabled or disabled.
        4. In guest, check if write_zeroes enabled or disabled.
        5. Do some IO tests on the disk.

    :param test: KVM test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def check_attribute_in_qtree(dev_id, name, excepted_val):
        """Check if discard and write-zeroes attribute work."""
        error_context.context("Check if %s attribute works." % name, test.log.info)
        qtree = qemu_qtree.QtreeContainer()
        qtree.parse_info_qtree(vm.monitor.info("qtree"))
        for node in qtree.get_nodes():
            if isinstance(node, qemu_qtree.QtreeDev) and node.qtree.get("id") == dev_id:
                _node = node.children[0].children[0]
                if _node.qtree.get("drive").endswith('_%s"' % dev_id):
                    if _node.qtree.get(name) is None:
                        test.fail(
                            "The qtree device %s has no property %s." % (dev_id, name)
                        )
                    elif _node.qtree.get(name) == excepted_val:
                        test.log.info(
                            'The "%s" matches with qtree device "%s"' "(%s).",
                            name,
                            dev_id,
                            excepted_val,
                        )
                        break
                    else:
                        test.fail(
                            'The "%s" mismatches with qtree device "%s"'
                            "(%s)." % (name, dev_id, excepted_val)
                        )
        else:
            test.error('No such "%s" qtree device.' % dev_id)

    def check_status_inside_guest(session, cmd, excepted_val):
        """Check if the discard or write-zeroes is enabled or disabled."""
        if excepted_val not in session.cmd(cmd, 600):
            test.fail('The output should be "%s"' % excepted_val)

    def get_data_disk_by_serial(session, image_tag):
        """Get the data disks by serial options."""
        match = re.search(
            r"serial=(\w+)", params["blk_extra_params_%s" % image_tag], re.M
        )
        drive_path = utils_misc.get_linux_drive_path(session, match.group(1))
        if not drive_path:
            test.error("Failed to get '%s' drive path" % image_tag)
        return drive_path

    def dd_test(session, target):
        """Do dd test on the data disk."""
        error_context.context("Do dd test on the data disk.", test.log.info)
        session.cmd(params["cmd_dd"].format(target), 600)

    data_tag = params["images"].split()[1]
    vm = env.get_vm(params["main_vm"])

    if params["start_vm"] == "no":
        params["start_vm"] = "yes"
        try:
            env_process.preprocess_vm(test, params, env, params["main_vm"])
        except virt_vm.VMCreateError as e:
            error_msg = params.get("error_msg")
            if error_msg not in str(e):
                test.fail(
                    'No found "%s" from the output of qemu:%s.' % (error_msg, str(e))
                )
        return

    vm.verify_alive()
    session = vm.wait_for_login()
    data_disk = get_data_disk_by_serial(session, data_tag)

    if params.get("attributes_checked"):
        for attr_name, val in ast.literal_eval(params["attributes_checked"]).items():
            check_attribute_in_qtree(data_tag, attr_name, val)

    if params.get("status_checked"):
        for cmd, val in ast.literal_eval(params["status_checked"]).items():
            check_status_inside_guest(session, params[cmd].format(data_disk), val)

    dd_test(session, data_disk)
