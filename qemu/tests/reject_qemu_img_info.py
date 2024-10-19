from avocado.utils import process
from virttest import data_dir, error_context
from virttest.qemu_storage import QemuImg

from qemu.tests.qemu_disk_img import QemuImgTest, generate_base_snapshot_pair


@error_context.context_aware
def run(test, params, env):
    """
    'qemu-img' lock tests.

    Verify it rejects to get information due to image lock.
    Including two tests:
    1. Create a base qcow2 image.
       Create an external snapshot.
       Boot vm using the base.
       'qemu-info' the snapshot with option "--backing-chain".
       'qemu-info' the snapshot with option "--backing-chain" and "-U".

    2. Create a base qcow2 image.
       Boot vm using the base.
       'qemu-info' the base.
       'qemu-info' the base with option "-U".

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _boot_vm(boot_img):
        error_context.context("Boot vm with %s." % boot_img, test.log.info)
        vm.params["images"] = boot_img
        vm.create()
        vm.verify_alive()

    def _qemu_img_info(info_img, force_share=False):
        error_context.context("Check qemu-img info with %s." % info_img, test.log.info)
        img_param = params.object_params(info_img)
        img = QemuImg(img_param, data_dir.get_data_dir(), info_img)
        img.info(force_share)

    def _verify_write_lock_err_msg(e, img_tag):
        error_context.context("Verify qemu-img write lock err msg.", test.log.info)
        img_param = params.object_params(img_tag)
        img = QemuImg(img_param, data_dir.get_data_dir(), img_tag)
        msgs = [
            '"write" lock',
            "Is another process using the image",
            img.image_filename,
        ]
        if not all(msg in e.result.stderr.decode() for msg in msgs):
            test.fail("Image lock information is not as expected.")

    def _qemu_img_info_to_verify_image_lock(boot_img, info_img, img_tag):
        _boot_vm(boot_img)
        try:
            _qemu_img_info(info_img)
        except process.CmdError as e:
            _verify_write_lock_err_msg(e, img_tag)
        else:
            test.fail("The image %s is not locked." % img_tag)
        try:
            _qemu_img_info(info_img, True)
        except process.CmdError:
            test.fail("qemu-img info %s failed." % info_img)

    vm = env.get_vm(params["main_vm"])
    if params.get("create_snapshot", "no") == "yes":
        gen = generate_base_snapshot_pair(params["image_chain"])
        base, snapshot = next(gen)
        # workaround to assign system disk's image_name to image_name_image1
        params["image_name_image1"] = params["image_name"]
        qit = QemuImgTest(test, params, env, snapshot)
        qit.create_snapshot()

        _qemu_img_info_to_verify_image_lock(base, snapshot, base)
    else:
        _qemu_img_info_to_verify_image_lock("image1", "image1", "image1")
