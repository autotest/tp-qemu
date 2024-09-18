import time

from avocado.utils import process
from virttest import env_process

from qemu.tests.qemu_disk_img import QemuImgTest, generate_base_snapshot_pair


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
        test.log.info("Create a qcow2 snapshot based on the os image.")
        # workaround to asign syetem disk's image_name to image_name_image1
        params["image_name_image1"] = params["image_name"]
        gen = generate_base_snapshot_pair(params["image_chain"])
        _, snapshot = next(gen)
        QemuImgTest(test, params, env, snapshot).create_snapshot()

    def _verify_write_lock_err_msg(test, img_file=None):
        test.log.info(
            "Verify qemu-img write lock err msg.",
        )
        msgs = ['"write" lock', "Is another process using the image"]
        # Avoid timing issues between writing to log and the check itself
        check_lock_timeout = params.get_numeric("check_lock_timeout", 5)
        time.sleep(check_lock_timeout)
        # Check expected error messages directly in the test log
        output = process.run(
            r"cat " + test.logfile + r"| grep '\[qemu output\]' | grep -v 'warning'",
            shell=True,
        ).stdout_text.strip()
        if img_file:
            msgs.append(img_file)
        if not all(msg in output for msg in msgs):
            test.fail("Image lock information is not as expected.")

    img_file = params["image_name"]

    if params.get("create_snapshot", "no") == "yes":
        _create_os_snapshot()
        env_process.preprocess_vm(test, params, env, "avocado-vt-vm1")
        vm1 = env.get_vm("avocado-vt-vm1")
    else:
        vm1 = env.get_vm("avocado-vt-vm1")
    vm2 = vm1.clone(name=params["second_vm_name"])

    test.log.info("Boot one vm from the base os image.")
    vm1.create()
    vm1.verify_status("running")

    if params.get("create_snapshot", "no") == "yes":
        # boot vm2 up using the external snapshot
        vm2.params["boot_drive_image1"] = "no"
        vm2.params["boot_drive_sn"] = "yes"
        img_file = None
        test.log.info("Boot a seconde vm from the snapshot.")
    else:
        test.log.info("Boot a seconde vm from the same os image.")

    try:
        vm2.create(params=vm2.params)
        vm2.verify_alive()
    except:
        _verify_write_lock_err_msg(test, img_file)
    else:
        test.fail("The second vm boot up, the image is not locked.")
    finally:
        vm1.verify_status("running")
