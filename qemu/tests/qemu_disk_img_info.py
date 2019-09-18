import logging

from virttest import env_process
from virttest import error_context
from virttest import storage

from avocado.utils import process
from qemu.tests import qemu_disk_img


class InfoTest(qemu_disk_img.QemuImgTest):

    def __init__(self, test, params, env, tag):
        self.tag = tag
        t_params = params.object_params(self.tag)
        super(InfoTest, self).__init__(test, t_params, env, self.tag)

    @error_context.context_aware
    def start_vm(self, t_params=None):
        """Start a vm and wait for its bootup."""
        error_context.context("start vm", logging.info)
        params = self.params.object_params(self.tag)
        if t_params:
            params.update(t_params)
        params["start_vm"] = "yes"
        params["images"] = self.tag
        vm_name = params["main_vm"]
        env_process.preprocess_vm(self.test, params, self.env, vm_name)
        vm = self.env.get_vm(vm_name)
        vm.verify_alive()
        login_timeout = int(self.params.get("login_timeout", 360))
        vm.wait_for_login(timeout=login_timeout)
        self.vm = vm
        return vm

    def clean(self):
        params = self.params
        for sn in params.get("image_chain").split()[1:]:
            _params = params.object_params(sn)
            _image = storage.get_image_filename(_params, self.data_dir)
            process.run("rm -f %s" % _image)


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
    check_files = []
    md5_dict = {}
    for idx, tag in enumerate(image_chain):
        params["image_chain"] = " ".join(image_chain[:idx + 1])
        info_test = InfoTest(test, params, env, tag)
        n_params = info_test.create_snapshot()
        info_test.start_vm(n_params)
        # check md5sum
        for _file in check_files:
            ret = info_test.check_file(_file, md5_dict[_file])
            if not ret:
                test.error("Check md5sum fail (file:%s)" % _file)
        # save file in guest
        t_file = params["guest_file_name_%s" % tag]
        md5 = info_test.save_file(t_file)
        if not md5:
            test.error("Fail to save tmp file")
        check_files.append(t_file)
        md5_dict[t_file] = md5
        info_test.destroy_vm()

        # get the disk image information
        info_test.check_backingfile()

    info_test.clean()
