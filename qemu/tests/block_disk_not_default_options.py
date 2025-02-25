from virttest import error_context, qemu_qtree

from provider import disk_utils
from provider.block_devices_plug import BlockDevicesPlug


@error_context.context_aware
def run(test, params, env):
    """
    Test the disk non-default options.

    Steps:
        1. Boot a VM with packed=true and page-per-vq=true
        2. Verify the packed and page-per-vq values
        3. Do some basic I/O operation in the VM
        4. Unplug and hotplug the disk
        5. Do again a basic I/O operation

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.
    """

    def verify_non_default_options(option_key, expected_value):
        """Verify the non-default values.
        :param option_key: the QEMU option to be checked.
        :param expected_value: the QEMU option expected value.
        """
        error_context.context(f"Verify {option_key} from monitor.", test.log.info)
        qtree = qemu_qtree.QtreeContainer()
        qtree_option_value = False
        try:
            qtree.parse_info_qtree(vm.monitor.info("qtree"))
        except AttributeError:
            test.cancel("Monitor doesn't support qtree skip this test")
        error_msg = (
            f"'{option_key}' value mismatch: expected %s but report from monitor is: %s"
        )

        for node in qtree.get_nodes():
            if (
                isinstance(node, qemu_qtree.QtreeDev)
                and node.qtree.get(option_key) == expected_value
            ):
                qtree_option_value = node.qtree.get(option_key)
                error_context.context(
                    f"The qtree_option_value: {qtree_option_value}", test.log.debug
                )

        if qtree_option_value != expected_value:
            error_msg = error_msg % (str(expected_value), qtree_option_value)
            test.fail(error_msg)

    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    session = vm.wait_for_login(timeout=360)

    qtree_check_images = params.get_list("qtree_check_images", "stg0")

    # To be configured by the user in the cfg
    tmp_dir = params.get("tmp_dir", None)
    disk_utils.execute_dd_on_disk_by_id(
        params, qtree_check_images[0], session, tmp_dir, test
    )

    for image in qtree_check_images:
        qtree_check_image = params.get_dict(f"qtree_check_{image}", "{}")
        if qtree_check_image:
            for option_key in qtree_check_image:
                error_context.base_context(
                    f"Options to verify: {option_key} {qtree_check_image[option_key]}",
                    test.log.debug,
                )
                verify_non_default_options(option_key, qtree_check_image[option_key])
        else:
            test.log.warning("There are no options to be checked in the qtree")

    plug = BlockDevicesPlug(vm)
    plug.unplug_devs_serial()
    plug.hotplug_devs_serial()
    disk_utils.execute_dd_on_disk_by_id(
        params, qtree_check_images[0], session, tmp_dir, test
    )
