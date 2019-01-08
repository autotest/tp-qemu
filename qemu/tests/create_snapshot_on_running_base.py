import logging

from qemu.tests.qemu_disk_img import QemuImgTest
from qemu.tests.qemu_disk_img import generate_base_snapshot_pair


def run(test, params, env):
    """
    qemu-img create a snapshot on a running base image.

    1. boot a guest up from a base image
    2. create a file on the base image disk, calculate its md5sum
    3. create a snapshot on the running base image
    4. shut the guest down and boot a guest from the snapshot
    5. check whether the file's md5sum stays same

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    gen = generate_base_snapshot_pair(params["image_chain"])
    base, snapshot = next(gen)
    file = params["guest_file_name"]

    logging.info("Boot a guest up from base image: %s, and create a"
                 " file %s on the disk." % (base, file))
    base_qit = QemuImgTest(test, params, env, base)
    base_qit.start_vm()
    md5 = base_qit.save_file(file)
    logging.info("Got %s's md5 %s from the base image disk." % (file, md5))

    logging.info("Create a snapshot %s on the running base image." % snapshot)
    params["image_name_image1"] = params["image_name"]
    sn_qit = QemuImgTest(test, params, env, snapshot)
    sn_qit.create_snapshot()

    base_qit.destroy_vm()
    logging.info("Boot the guest up from snapshot image: %s, and verify the"
                 " file %s's md5 on the disk." % (snapshot, file))
    sn_qit.start_vm()
    if not sn_qit.check_file(file, md5):
        test.fail("The file %s's md5 on base and"
                  " snapshot are different." % file)

    for qit in (base_qit, sn_qit):
        qit.clean()
