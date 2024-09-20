import os

from avocado.utils import process
from virttest import data_dir, utils_package
from virttest.qemu_io import QemuIOSystem
from virttest.qemu_storage import QemuImg


def run(test, params, env):
    """
    qemu-img supports convert coroutines complete.

    1. create source and target images, write 0 into
       the entire source image through qemu-io
    2. install valgrind
    3. inject error to qemu-img convert and inspect the result
    4. remove valgrind

    :param test: Qemu test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _get_img_obj_and_params(tag):
        """Get an QemuImg object and its params based on the tag."""
        img_param = params.object_params(tag)
        img = QemuImg(img_param, data_dir.get_data_dir(), tag)
        return img, img_param

    def _qemu_io(img, cmd):
        """Run qemu-io cmd to a given img."""
        test.log.info("Run qemu-io %s", img.image_filename)
        q = QemuIOSystem(test, params, img.image_filename)
        q.cmd_output(cmd, 120)

    def _create_error_cfg(file):
        test.log.info("Create error cfg %s.", file)
        error_cfg = (
            '[inject-error]\nevent = "write_aio"\n' 'sector = "819200"\nonce = "on"'
        )
        with open(file, "w") as cfg:
            cfg.write(error_cfg)

    def _inject_error_and_verify(file):
        try:
            pkg = utils_package.LocalPackageMgr("valgrind")
            pkg.install()
            _create_error_cfg(file)
            cmd = (
                "valgrind --soname-synonyms=somalloc=libtcmalloc.so "
                "qemu-img convert -npWO qcow2 source.qcow2 "
                "blkdebug:%s:target.qcow2" % file
            )
            stderr = process.run(cmd, ignore_status=True).stderr_text
            if "ERROR SUMMARY: 0 errors from 0 contexts" not in stderr:
                test.fail("There should be no errors in the summary.")
        finally:
            os.unlink(file)
            pkg.remove()

    test.log.info("Create source and target images.")
    for tag in params["images"].split():
        img, img_param = _get_img_obj_and_params(tag)
        img.create(img_param)
        if tag == "source":
            _qemu_io(img, "write 0 1G")

    _inject_error_and_verify(params["error_cfg"])
