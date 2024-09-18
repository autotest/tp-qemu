from avocado.utils import process
from virttest import utils_misc

from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest


class BlockdevMirrorQemuioTarget(BlockdevMirrorNowaitTest):
    """
    Qemuio target image during mirror
    """

    def qemuio_target_image(self):
        tag = self._target_images[0]
        image_params = self.params.object_params(tag)
        image = self.disk_define_by_params(image_params, tag)
        filename = image.image_filename
        fmt = image.image_format
        qemu_io = utils_misc.get_qemu_io_binary(self.params)
        qemuio_cmd = self.params.get("qemuio_cmd") % (qemu_io, fmt, filename)
        try:
            process.run(qemuio_cmd, shell=True)
        except process.CmdError as e:
            if self.params["error_msg"] not in e.result.stderr.decode():
                self.test.fail(
                    "Write to used image failed with error: %s" % e.result.stderr
                )
        else:
            self.test.fail("Can qemu-io a using image")

    def do_test(self):
        self.blockdev_mirror()
        self.qemuio_target_image()


def run(test, params, env):
    """
    Qemuio target image during mirror

    test steps:
        1. boot VM with 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a local fs image for mirror to VM via qmp commands
        5. do blockdev-mirror
        6. qemu-io target image during mirror, this operation will
           be not allowed and error will be hit.

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    qemuio_when_ready = BlockdevMirrorQemuioTarget(test, params, env)
    qemuio_when_ready.run_test()
