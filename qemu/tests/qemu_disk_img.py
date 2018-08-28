import os
import re
import logging

from avocado.utils import process

from virttest import data_dir
from virttest import env_process
from virttest import error_context
from virttest import storage
from virttest import qemu_storage
from virttest import utils_test
from virttest import utils_misc
from virttest import error_context
from avocado.core import exceptions


class QemuImgTest(qemu_storage.QemuImg):

    def __init__(self, test, params, env, tag):
        self.vm = None
        self.test = test
        self.params = params
        self.env = env
        self.tag = tag
        self.data_dir = data_dir.get_data_dir()
        self.trash = []
        t_params = params.object_params(tag)
        super(QemuImgTest, self).__init__(t_params, self.data_dir, tag)

    @error_context.context_aware
    def create_snapshot(self, t_params=None):
        """
        create snapshot image file
        """
        error_context.context("create snapshot image")
        params = self.params.object_params(self.tag)
        if t_params:
            params.update(t_params)
        if len(params.get("image_chain", "").split()) < 2:
            return {}
        snapshot = storage.get_image_filename(params, self.data_dir)
        if os.path.exists(snapshot):
            process.run("rm -f %s" % snapshot)
        super(QemuImgTest, self).create(params)
        self.trash.append(snapshot)
        return params

    @error_context.context_aware
    def start_vm(self, t_params=None):
        """
        Start a vm and wait for it bootup;
        """
        error_context.context("start vm", logging.info)
        params = self.params.object_params(self.tag)
        if t_params:
            params.update(t_params)
        base_image = params.get("images", "image1").split()[0]
        params["start_vm"] = "yes"
        try:
            del params["image_name_%s" % base_image]
            del params["image_format_%s" % base_image]
        except KeyError:
            pass
        vm_name = params["main_vm"]
        env_process.preprocess_vm(self.test, params, self.env, vm_name)
        vm = self.env.get_vm(vm_name)
        vm.verify_alive()
        login_timeout = int(self.params.get("login_timeout", 360))
        vm.wait_for_login(timeout=login_timeout)
        self.vm = vm
        return vm

    @error_context.context_aware
    def __create_file(self, dst):
        logging.info("create tmp file on host")
        if not self.vm:
            return False
        src = self.params["tmp_file_name"]
        cmd = self.params["file_create_cmd"] % src
        process.run(cmd, shell=True)
        self.vm.copy_files_to(src, dst)
        self.trash.append(src)
        return True

    def __md5sum(self, dst):
        logging.info("calculate MD5 of the file")
        if not self.vm:
            return False
        login_timeout = int(self.params.get("login_timeout", 360))
        session = self.vm.wait_for_login(timeout=login_timeout)
        md5bin = self.params.get("md5sum_bin", "md5sum")
        cmd = "%s %s" % (md5bin, dst)
        status, output = session.cmd_status_output(cmd)
        if status != 0:
            logging.error("Execute '%s' with failures('%s') " % (cmd, output))
            return None
        md5 = re.findall(r"\w{32}", output)[0]
        return md5

    @error_context.context_aware
    def save_file(self, dst):
        login_timeout = int(self.params.get("login_timeout", 360))
        cmd = self.params.get("sync_bin", "sync")
        error_context.context("save file('%s') md5sum in guest" % dst,
                              logging.info)
        self.__create_file(dst)
        session = self.vm.wait_for_login(timeout=login_timeout)
        logging.info("sync guest data")
        cmd = utils_misc.set_winutils_letter(session, cmd)
        status, output = session.cmd_status_output(cmd)
        if status != 0:
            logging.error("Execute '%s' with failures('%s') " % (cmd, output))
            return None
        session.close()
        return self.__md5sum(dst)

    @error_context.context_aware
    def check_file(self, dst, md5):
        error_context.context("check file('%s') md5sum in guest" % dst,
                              logging.info)
        if md5 != self.__md5sum(dst):
            err = ("Md5 value does not match. "
                   "Expected value: %s Actual value: %s" %
                   (md5, self.__md5sum(dst)))
            logging.error(err)
            return False
        return True

    @error_context.context_aware
    def destroy_vm(self):
        error_context.context("destroy vm", logging.info)
        if self.vm:
            self.vm.destroy()
        self.vm = None

    @error_context.context_aware
    def check_image(self, t_params=None):
        error_context.context("check image file ('%s')" % self.image_filename,
                              logging.info)
        t_params = t_params or {}
        return super(QemuImgTest, self).check_image(t_params, self.data_dir)

    @error_context.context_aware
    def get_info(self):
        error_context.context("get image file ('%s')" % self.image_filename)
        return super(QemuImgTest, self).info()

    @error_context.context_aware
    def verify_info(self, params=None):
        """
        verify option is applied to image file correctly
        """
        error_context.context("verify option of converted image", logging.info)
        image_filename = storage.get_image_filename(params, self.data_dir)
        info = utils_test.get_image_info(image_filename)
        avalue = evalue = ""
        for option in params.objects("option_verified"):
            avalue = info.get(option)
            if option == "format":
                evalue = params.get("image_format")
            elif option == "lcounts":
                if params.get("lazy_refcounts") == "on":
                    evalue = "true"
                elif params.get("lazy_refcounts") == "off":
                    evalue = "false"
            elif option == "csize":
                csize = params.get("cluster_size")
                evalue = int(float(utils_misc.normalize_data_size(csize, "B")))
            elif option == "sparse_size":
                if info.get("dsize") < info.get("vsize"):
                    avalue = info.get("dsize")
                    evalue = info.get("vsize")
            else:
                evalue = params.get(option)
            if avalue is not None and avalue != evalue:
                msg = "Get wrong %s from image %s!" % (option, image_filename)
                msg += "Expect: %s, actual: %s" % (evalue, avalue)
                self.test.fail(msg)

    @error_context.context_aware
    def check_backingfile(self):
        error_context.context("check image('%s') backing file" %
                              self.image_filename, logging.info)
        out = self.get_info()
        try:
            backingfile = re.search(r'backing file: +(.*)', out, re.M).group(1)
            if not self.base_tag or self.base_tag == "null":
                msg = ("Expected backing file is null")
                msg += " Actual backing file: %s" % backingfile
                raise exceptions.TestFail(msg)
            elif backingfile != self.base_image_filename:
                msg = ("Expected backing file: %s" % self.base_image_filename)
                msg += " Actual backing file: %s" % backingfile
                raise exceptions.TestFail(msg)
        except AttributeError:
            if self.base_tag and self.base_tag != "null":
                msg = ("Could not find backing file for image '%s'" %
                       self.image_filename)
                raise exceptions.TestFail(msg)

    @error_context.context_aware
    def clean(self):
        error_context.context("clean up useless images")
        self.destroy_vm()
        for temp in self.trash:
            process.run("rm -f %s" % temp)


def run(test, params, env):
    pass
