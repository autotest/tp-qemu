import re
import logging

from virttest import qemu_storage
from virttest import lvm
from virttest import error_context
from avocado.utils import process

from autotest.client.shared import error


class NegativeRebase(qemu_storage.QemuImg):

    def __init__(self, test, params, env):
        self.test = test
        self.params = params
        self.env = env
        self.data_dir = "/dev/%s" % params.get("vg_name")
        self.lvmdevice = None

    def setup_lvm(self):
        """
        Setup a lvm environment and create logical volume:

        :return logical volume object
        """
        self.params["pv_name"] = self.params.get("image_name")
        lvmdevice = lvm.LVM(self.params)
        error_context.context("Setup lvms", logging.info)
        for lv_name in self.params.objects("lv_name_list"):
            self.params["lv_name"] = lv_name
            lvmdevice.setup()
        self.lvmdevice = lvmdevice

    def start_test(self):
        """
        Main function to run the negative test of rebase:
        """
        rebase_chain = self.params.get("rebase_list", "").split(";")
        self.setup_lvm()
        try:
            error_context.context("Create images on lvms", logging.info)
            for image_name in self.params.objects("images"):
                filename = "%s/%s" % (self.data_dir,
                                      self.params["image_name_%s" % image_name])
                self.params.update(
                    {"image_name_%s" % image_name: filename,
                     "image_size_%s" % image_name: self.params["lv_size"]})
                t_params = self.params.object_params(image_name)
                qemu_image = qemu_storage.QemuImg(t_params,
                                                  self.data_dir, image_name)
                logging.info("Create image('%s') on %s." %
                             (image_name, qemu_image.storage_type))
                qemu_image.create(t_params)
            error_context.context("Rebase snapshot to backingfile",
                                  logging.info)
            for images in rebase_chain:
                output = ""
                cache_mode = self.params.get("cache_mode")
                images = map(lambda x: x.strip(), images.split(">"))
                try:
                    image = images[0]
                    base = images[1]
                except IndexError:
                    msg = "Invalid format of'rebase_chain' params \n"
                    msg += "format like: 'image > base;image> base2'"
                    raise error.TestError(msg)
                negtive_test = self.params.get("negtive_test_%s" % image, "no")
                self.params["image_chain"] = " ".join([base, image])
                self.params["base_image_filename"] = image
                t_params = self.params.object_params(image)
                rebase_test = qemu_storage.QemuImg(t_params,
                                                   self.data_dir, image)
                try:
                    rebase_test.rebase(t_params, cache_mode)
                    if negtive_test == "yes":
                        msg = "Fail to trigger negative image('%s') rebase" % image
                        raise error.TestFail(msg)
                except process.CmdError, err:
                    output = err.result.stderr
                    logging.info("Rebase image('%s') failed: %s." %
                                 (image, output))
                    if negtive_test == "no":
                        msg = "Fail to rebase image('%s'): %s" % (image, output)
                        raise error.TestFail(msg)
                    if "(core dumped)" in output:
                        msg = "qemu-img core dumped when change"
                        msg += " image('%s') backing file to %s" % (image, base)
                        raise error.TestFail(msg)
                image_info = rebase_test.info()
                if not image_info:
                    msg = "Fail to get image('%s') info" % image
                    raise error.TestFail(msg)
                backingfile = re.search(r'backing file: +(.*)',
                                        image_info, re.M)
                base_name = rebase_test.base_image_filename
                if not output:
                    if not backingfile:
                        msg = "Expected backing file: %s" % base_name
                        msg += " Actual backing file is null!"
                        raise error.TestFail(msg)
                    elif base_name not in backingfile.group(0):
                        msg = "Expected backing file: %s" % base_name
                        msg += " Actual backing file: %s" % backingfile
                        raise error.TestFail(msg)
        finally:
            try:
                self.lvmdevice.cleanup()
            except Exception:
                logging.error("Failed to remove useless lv, vg and pv")


@error_context.context_aware
def run(test, params, env):
    """
    qemu-img rebase negative test:
    1) create lvms on iscsi device
    2) create image base, snapshot sn1 and image sn2
    3) rebase image sn2 to image base
    4) check result. Case passed only if one of rebase
    opearations failed and no core dump generated

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    nrebase_test = NegativeRebase(test, params, env)
    nrebase_test.start_test()
