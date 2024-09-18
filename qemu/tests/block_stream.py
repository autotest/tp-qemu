import logging
import re

from avocado.utils import process
from virttest import env_process, error_context, utils_misc

from qemu.tests import blk_stream

LOG_JOB = logging.getLogger("avocado.test")


class BlockStreamTest(blk_stream.BlockStream):
    def get_image_size(self, image_file):
        try:
            qemu_img = utils_misc.get_qemu_img_binary(self.params)
            cmd = "%s info %s" % (qemu_img, image_file)
            LOG_JOB.info("Try to get image size via qemu-img info")
            info = process.system_output(cmd)
            size = int(re.findall(r"(\d+) bytes", info)[0])
        except process.CmdError:
            LOG_JOB.info(
                "qemu-img info failed(it happens because later qemu"
                " distributions prevent it access a running image.)."
                " Now get image size via qmp interface 'query-block'"
            )
            blocks_info = self.vm.monitor.info("block")
            for block in blocks_info:
                info = block["inserted"]
                if image_file == info["file"]:
                    size = info["image"]["virtual-size"]
        if size:
            return size
        return 0


@error_context.context_aware
def run(test, params, env):
    """
    Test block streaming functionality.

    1) create live snapshot image sn1
    3) Request for block-stream
    4) Wait till the block job finishs
    5) Check for backing file in sn1
    6) Check for the size of the sn1 should not exceeds image.img
    """
    tag = params.get("source_image", "image1")
    stream_test = BlockStreamTest(test, params, env, tag)
    try:
        image_file = stream_test.get_image_file()
        image_size = stream_test.get_image_size(image_file)
        stream_test.create_snapshots()
        backingfile = stream_test.get_backingfile()
        if not backingfile:
            test.fail("Backing file is not available in the " "backdrive image")
        test.log.info("Image file: %s", stream_test.get_image_file())
        test.log.info("Backing file: %s", backingfile)
        stream_test.start()
        stream_test.wait_for_finished()
        backingfile = stream_test.get_backingfile()
        if backingfile:
            test.fail("Backing file is still available in the " "backdrive image")
        target_file = stream_test.get_image_file()
        target_size = stream_test.get_image_size(target_file)
        error_context.context("Compare image size", test.log.info)
        if image_size < target_size:
            test.fail(
                "Compare %s image, size of %s increased"
                "(%s -> %s)" % (image_file, target_file, image_size, target_size)
            )
        stream_test.verify_alive()
        stream_test.vm.destroy()
        vm_name = params["main_vm"]
        env_process.preprocess_vm(test, params, env, vm_name)
        vm = env.get_vm(vm_name)
        stream_test.vm = vm
        stream_test.verify_alive()
    finally:
        stream_test.clean()
