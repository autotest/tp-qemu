import logging
import os

from virttest import utils_misc

from qemu.tests import blk_stream

LOG_JOB = logging.getLogger("avocado.test")


class BlockStreamCheckBackingfile(blk_stream.BlockStream):
    def __init__(self, test, params, env, tag):
        super(BlockStreamCheckBackingfile, self).__init__(test, params, env, tag)

    def check_backingfile(self):
        """
        check no backingfile found after stream job done via qemu-img info;
        """
        fail = False
        LOG_JOB.info("Check image file backing-file")
        backingfile = self.get_backingfile("qemu-img")
        if backingfile:
            img_file = self.get_image_file()
            LOG_JOB.debug(
                "Got backing-file: %s by 'qemu-img info %s'", backingfile, img_file
            )
            fail |= bool(backingfile)
        backingfile = self.get_backingfile("monitor")
        if backingfile:
            LOG_JOB.debug(
                "Got backing-file: %s by 'info/query block' in %s monitor",
                backingfile,
                self.vm.monitor.protocol,
            )
            fail |= bool(backingfile)
        if fail:
            msg = "Unexpected backing file found, there should be " "no backing file"
            self.test.fail(msg)

    def check_backingfile_exist(self):
        if not self.base_image:
            self.test.error("No backing file specified.")
        backingfile = self.get_backingfile()
        if backingfile != self.base_image:
            msg = "The backing file from monitor does not meet expectation. "
            msg += "It should be %s, now is %s." % (self.base_image, backingfile)
            self.test.fail(msg)

    def check_imagefile(self):
        """
        verify current image file is expected image file
        """
        params = self.parser_test_args()
        exp_img_file = params["expected_image_file"]
        exp_img_file = utils_misc.get_path(self.data_dir, exp_img_file)
        LOG_JOB.info("Check image file is '%s'", exp_img_file)
        img_file = self.get_image_file()
        if exp_img_file != img_file:
            msg = "Excepted image file: %s," % exp_img_file
            msg += "Actual image file: %s" % img_file
            self.test.fail(msg)

    def set_backingfile(self):
        """
        Set values for backing-file option
        """
        self.base_image = self.image_file
        absolute_path = self.params["absolute_path"]
        if absolute_path == "yes":
            backing_file = self.base_image
        else:
            backing_file = os.path.relpath(self.base_image)
        self.ext_args.update({"backing-file": backing_file})


def run(test, params, env):
    """
    block_stream.check_backingfile test:
    1). boot up vm and create snapshots;
    2). start block steam job, then wait block job done;
    3). check backing-file in monitor and qemu-img command;
    4). verify image file is excepted image file;
    5). vierfy guest is alive;

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    backingfile_test = BlockStreamCheckBackingfile(test, params, env, tag)
    try:
        backingfile_test.create_snapshots()
        backingfile_test.action_before_start()
        backingfile_test.start()
        backingfile_test.action_after_finished()
    finally:
        backingfile_test.clean()
