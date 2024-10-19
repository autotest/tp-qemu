from virttest import data_dir, error_context, qemu_storage, utils_test


@error_context.context_aware
def run(test, params, env):
    """
    Downgrade qcow2 image version:
    1) Get the version of the image
    2) Compare the version with expect version. If they are different,
    Amend the image with new version
    3) Check the amend result

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    ver_to = params.get("lower_version_qcow2", "0.10")
    error_context.context(
        "Downgrade qcow2 image version to '%s'" % ver_to, test.log.info
    )
    image = params.get("images").split()[0]
    t_params = params.object_params(image)
    qemu_image = qemu_storage.QemuImg(t_params, data_dir.get_data_dir(), image)
    ver_from = utils_test.get_image_version(qemu_image)
    utils_test.update_qcow2_image_version(qemu_image, ver_from, ver_to)
    actual_compat = utils_test.get_image_version(qemu_image)
    if actual_compat != ver_to:
        err_msg = "Fail to downgrade qcow2 image version!"
        err_msg += "Actual: %s, expect: %s" % (actual_compat, ver_to)
        test.fail(err_msg)
