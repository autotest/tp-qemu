import re

from virttest.qemu_monitor import QMPCmdError

from provider.blockdev_stream_base import BlockDevStreamTest


class BlockdevStreamNoneExistedOverlay(BlockDevStreamTest):
    """Do block-stream to an non-existed snapshot"""

    def pre_test(self):
        # vm will be started by VT, and no image will be created
        pass

    def post_test(self):
        # vm will be stopped by VT, and no image will be removed
        pass

    def do_test(self):
        try:
            self.main_vm.monitor.cmd(
                "block-stream", {"device": self.params["none_existed_overlay_node"]}
            )
        except QMPCmdError as e:
            error_msg = self.params.get("error_msg")
            if not re.search(error_msg, str(e)):
                self.test.fail("Unexpected error: %s" % str(e))
        else:
            self.test.fail("block-stream succeeded unexpectedly")


def run(test, params, env):
    """
    Do block-stream to an non-existed snapshot
    test steps:
        1. boot VM with a data image
        2. do block-stream to an non-existed snapshot
        3. check the proper error message should show out
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamNoneExistedOverlay(test, params, env)
    stream_test.run_test()
