import logging

from avocado.utils import process
from virttest import env_process

from qemu.tests.qemu_disk_img import QemuImgTest
from qemu.tests.qemu_disk_img import generate_base_snapshot_pair


def run(test, params, env):
    """
    QEMU img lcok reject boot tests.

    1. create an external snapshot based on a os image (optional)
    2. boot one vm from the os image
    3  boot another vm from the same base os image or the snapshot
    4. verify qemu image lock

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    def _create_os_snapshot():
        """Crate one external snapshot based on the os image."""
        logging.info("Create a qcow2 snapshot based on the os image.")
        # workaround to asign syetem disk's image_name to image_name_image1
        params["image_name_image1"] = params["image_name"]
        gen = generate_base_snapshot_pair(params["image_chain"])
        _, snapshot = next(gen)
        QemuImgTest(test, params, env, snapshot).create_snapshot()

    def _verify_write_lock_err_msg(test, output, img_file=None):
        logging.info("Verify qemu-img write lock err msg.",)
        msgs = ['"write" lock',
                'Is another process using the image']
        if img_file:
            msgs.append(img_file)
        if not all(msg in output for msg in msgs):
            test.fail("Image lock information is not as expected.")

    img_file = params["image_name"]

    if params.get("create_snapshot", "no") == "yes":
        _create_os_snapshot()
        env_process.preprocess_vm(test, params, env, "avocado-vt-vm1")
        vm1 = env.get_vm("avocado-vt-vm1")
        # remove sn in 'images' to prevent boot with two images
        vm1.params["images"] = "image1"
    else:
        vm1 = env.get_vm("avocado-vt-vm1")
    vm2 = vm1.clone(name=params["second_vm_name"])

    logging.info("Boot one vm from the base os image.")
    vm1.create()
    vm1.verify_status("running")

    if params.get("create_snapshot", "no") == "yes":
        # boot vm2 up using the external snapshot
        vm2.params["image_name_image1"] = params["image_name_sn"]
        vm2.params["image_format_image1"] = params["image_format_sn"]
        img_file = None
        logging.info("Boot a seconde vm from the snapshot.")
    else:
        logging.info("Boot a seconde vm from the same os image.")

    try:
        vm2.devices, _ = vm2.make_create_command()
        output = process.run(vm2.devices.cmdline(),
                             shell=True, ignore_status=True)
        if output.exit_status == 0:
            test.fail("The second vm boot up, the image is not locked.")
        _verify_write_lock_err_msg(test, output.stderr_text, img_file)
    finally:
        vm1.verify_status("running")
