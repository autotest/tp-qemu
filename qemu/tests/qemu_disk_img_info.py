import re

from autotest.client import utils
from autotest.client.shared import error

from virttest import storage

from qemu.tests import qemu_disk_img


class InfoTest(qemu_disk_img.QemuImgTest):

    def __init__(self, test, params, env, tag):
        self.tag = tag
        t_params = params.object_params(self.tag)
        super(InfoTest, self).__init__(test, t_params, env, self.tag)

    def check_backingfile(self, out={}):
        backingfile = re.search(r'backing file: +(.*)', out, re.M)
        if self.base_tag:
            if backingfile:
                if not (self.base_image_filename in backingfile.group(0)):
                    msg = "Expected backing file: %s" % self.base_image_filename
                    msg += " Actual backing file: %s" % backingfile
                    raise error.TestFail(msg)
            else:
                msg = ("Could not find backing file for image '%s'" %
                       self.image_filename)
                raise error.TestFail(msg)
        else:
            if backingfile:
                msg = "Expected backing file is null"
                msg += " Actual backing file: %s" % backingfile
                raise error.TestFail(msg)

    def clean(self):
        params = self.params
        for sn in params.get("image_chain").split()[1:]:
            _params = params.object_params(sn)
            _image = storage.get_image_filename(_params, self.data_dir)
            utils.run("rm -f %s" % _image)


def run(test, params, env):
    """
    'qemu-img' info function test:

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    base_image = params.get("images", "image1").split()[0]
    params.update(
        {"image_name_%s" % base_image: params["image_name"],
         "image_format_%s" % base_image: params["image_format"]})
    image_chain = params.get("image_chain", "").split()
    for idx, tag in enumerate(image_chain):
        params["image_chain"] = " ".join(image_chain[:idx + 1])
        info_test = InfoTest(test, params, env, tag)
        n_params = info_test.create_snapshot()
        info_test.start_vm(n_params)
        t_file = params["guest_file_name_%s" % tag]
        md5 = info_test.save_file(t_file)
        if not md5:
            raise error.TestError("Fail to save tmp file")
        info_test.destroy_vm()

        # get the disk image information
        out = info_test.info(params)
        info_test.check_backingfile(out)
        info_test.start_vm(n_params)

        # check md5sum after info
        ret = info_test.check_file(t_file, md5)
        if not ret:
            raise error.TestError("Check md5sum fail (file:%s)" % t_file)
        info_test.destroy_vm()

    info_test.clean()
