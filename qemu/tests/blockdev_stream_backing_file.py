import os

from provider.blockdev_stream_base import BlockDevStreamTest


class BlockdevStreamBackingFileTest(BlockDevStreamTest):
    """Do block-stream with backing-file set"""

    def __init__(self, test, params, env):
        super(BlockdevStreamBackingFileTest, self).__init__(test, params, env)
        image = self.base_image.image_filename
        self._stream_options["base"] = image
        if self.params.get_boolean("with_abspath"):
            self._stream_options["backing-file"] = image
        else:
            self._stream_options["backing-file"] = os.path.relpath(image)

    def _compare_backing(self, block):
        bk = block.get("image", {})
        if bk.get("backing-filename") != self._stream_options["backing-file"]:
            self.test.fail(
                "backing filename changed: %s vs %s"
                % (bk.get("backing-filename"), self._stream_options["backing-file"])
            )

    def check_backing_file(self):
        for item in self.main_vm.monitor.query("block"):
            if self.base_tag in item["qdev"]:
                self._compare_backing(item.get("inserted", {}))
                break
        else:
            self.test.fail("Failed to get device: %s" % self.base_tag)

    def do_test(self):
        self.create_snapshot()
        self.blockdev_stream()
        self.check_backing_file()


def run(test, params, env):
    """
    Basic block stream test with backing-file option

    test steps:
        1. boot VM
        2. add a snapshot image for system image
        3. take snapshot for system image
        4. do block-stream for system image and wait job done
        5. check backing-file can be found in the output of query-block

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamBackingFileTest(test, params, env)
    stream_test.run_test()
