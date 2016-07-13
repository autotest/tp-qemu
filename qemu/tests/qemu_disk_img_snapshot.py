import logging
from autotest.client.shared import error
from qemu.tests import qemu_disk_img


@error.context_aware
def run(test, params, env):
    """
    'qemu-img' snapshot functions test:

    Params:
    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.

    Test steps:
    1. save file md5sum before create snapshot.
    2. create snapshot and check the result.
    3. change tmp file before apply snapshot.
    4. apply snapshot.
    5. check md5sum after apply snapshot.
    """

    base_image = params.get("images", "image1").split()[0]
    params.update(
        {"image_name_%s" % base_image: params["image_name"],
         "image_format_%s" % base_image: params["image_format"]})
    t_file = params["guest_file_name"]
    snapshot_test = qemu_disk_img.QemuImgTest(test, params, env, base_image)

    error.context("Step1. save file md5sum before create snapshot.", logging.info)
    snapshot_test.start_vm(params)
    md5 = snapshot_test.save_file(t_file)
    if not md5:
        raise error.TestError("Fail to save tmp file.")
    snapshot_test.destroy_vm()

    error.context("Step2. create snapshot and check the result.", logging.info)
    snapshot_tag = snapshot_test.snapshot_create()
    output = snapshot_test.snapshot_list()
    if snapshot_tag not in output:
        raise error.TestFail("Snapshot created failed or missed;"
                             "snapshot list is: \n%s" % output)

    error.context("Step3. change tmp file before apply snapshot", logging.info)
    snapshot_test.start_vm(params)
    change_md5 = snapshot_test.save_file(t_file)
    if not change_md5 and change_md5 == md5:
        raise error.TestError("Fail to change tmp file.")
    snapshot_test.destroy_vm()

    error.context("Step4. apply snapshot.", logging.info)
    snapshot_test.snapshot_apply()
    snapshot_test.snapshot_del()

    error.context("Step5. check md5sum after apply snapshot.", logging.info)
    snapshot_test.start_vm(params)
    ret = snapshot_test.check_file(t_file, md5)
    if not ret:
        raise error.TestError("image content changed after apply snapshot")

    snapshot_test.clean()
