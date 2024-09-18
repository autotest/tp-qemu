from avocado.utils import process
from virttest import data_dir, error_context
from virttest.qemu_storage import QemuImg

from qemu.tests.qemu_disk_img import QemuImgTest, generate_base_snapshot_pair


@error_context.context_aware
def run(test, params, env):
    """
    'qemu-img' lock tests.

    Verify it supports to get information of a running image.
    Including three tests:
    1. Create a raw/luks image.
       Boot vm using this image.
       'qemu-info' the image.
    2. Create a base qcow2 image.
       Create an external snapshot.
       Boot vm using the base.
       'qemu-info' the snapshot.
    3. Create a base qcow2 image.
       Create an external snapshot.
       Boot vm using the snapshot.
       'qemu-info' the base.

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _boot_vm(boot_img):
        error_context.context("Boot vm with %s." % boot_img, test.log.info)
        vm.params["images"] = boot_img
        vm.create()
        vm.verify_alive()

    def _qemu_img_info(info_img):
        error_context.context("Check qemu-img info with %s." % info_img, test.log.info)
        img_param = params.object_params(info_img)
        img = QemuImg(img_param, data_dir.get_data_dir(), info_img)
        try:
            img.info()
        except process.CmdError:
            test.fail("qemu-img info %s failed." % info_img)

    def _qemu_img_info_while_vm_running(boot_img, info_img):
        _boot_vm(boot_img)
        _qemu_img_info(info_img)

    vm = env.get_vm(params["main_vm"])
    if params.get("create_snapshot", "no") == "yes":
        # create an external snapshot
        gen = generate_base_snapshot_pair(params["image_chain"])
        base_snapshot_pair = base, snapshot = next(gen)
        # workaround to assign system disk's image_name to image_name_image1
        params["image_name_image1"] = params["image_name"]
        qit = QemuImgTest(test, params, env, snapshot)
        qit.create_snapshot()

        if params.get("boot_with_snapshot", "no") == "yes":
            # reverse base snap pair, so boot vm with snapshot
            base_snapshot_pair.reverse()
        _qemu_img_info_while_vm_running(*base_snapshot_pair)
    else:
        # boot and info same img, raw only
        _qemu_img_info_while_vm_running("image1", "image1")
