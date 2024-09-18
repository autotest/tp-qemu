import re

from avocado.utils import process
from virttest import data_dir, error_context, qemu_storage


@error_context.context_aware
def run(test, params, env):
    """
    qemu-img rebase negative test:
    1) Create images for testing using avocado
    2) Change the backing file of snapshot
    3) Check result. Case passed only if expected rebase
    opearations are failed and no core dump is generated

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    rebase_chain = params.get("rebase_list", "").split(";")
    error_context.context("Change the backing file of snapshot", test.log.info)
    for images in rebase_chain:
        output = ""
        images = re.split(r"\s*>\s*", images)
        try:
            image = images[0]
            base = images[1]
        except IndexError:
            msg = "Invalid format of'rebase_chain' params \n"
            msg += "format like: 'image > base;image> base2'"
            test.error(msg)
        negtive_test = params.get("negtive_test_%s" % image, "no")
        params["image_chain"] = " ".join([base, image])
        params["base_image_filename"] = image
        t_params = params.object_params(image)
        cache_mode = t_params.get("cache_mode", None)
        rebase_test = qemu_storage.QemuImg(t_params, data_dir.get_data_dir(), image)
        try:
            rebase_test.rebase(t_params, cache_mode)
            if negtive_test == "yes":
                msg = "Fail to trigger negative image('%s') rebase" % image
                test.fail(msg)
        except process.CmdError as err:
            output = err.result.stderr.decode()
            test.log.info("Rebase image('%s') failed: %s.", image, output)
            if negtive_test == "no":
                msg = "Fail to rebase image('%s'): %s" % (image, output)
                test.fail(msg)
            if "(core dumped)" in output:
                msg = "qemu-img core dumped when change"
                msg += " image('%s') backing file to %s" % (image, base)
                test.fail(msg)
        image_info = rebase_test.info()
        if not image_info:
            msg = "Fail to get image('%s') info" % image
            test.fail(msg)
        backingfile = re.search(r"backing file: +(.*)", image_info, re.M)
        base_name = rebase_test.base_image_filename
        if not output:
            if not backingfile:
                msg = "Expected backing file: %s" % base_name
                msg += " Actual backing file is null!"
                test.fail(msg)
            elif base_name not in backingfile.group(0):
                msg = "Expected backing file: %s" % base_name
                msg += " Actual backing file: %s" % backingfile
                test.fail(msg)
