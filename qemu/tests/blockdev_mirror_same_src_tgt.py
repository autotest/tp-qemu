from virttest.qemu_monitor import QMPCmdError

from provider.backup_utils import blockdev_mirror_qmp_cmd
from provider.blockdev_mirror_base import BlockdevMirrorBaseTest


class BlockdevMirrorSameSrcTgt(BlockdevMirrorBaseTest):
    """
    Do block mirror from source node to source node
    """

    def prepare_test(self):
        self.prepare_main_vm()

    def post_test(self):
        """vt takes care of post steps"""
        pass

    def blockdev_mirror(self):
        try:
            cmd, args = blockdev_mirror_qmp_cmd(
                self._source_nodes[0], self._source_nodes[0], **self._backup_options[0]
            )
            self.main_vm.monitor.cmd(cmd, args)
        except QMPCmdError as e:
            if self.params["error_msg"] not in str(e):
                self.test.fail("Unexpected error: %s" % str(e))
        else:
            self.test.fail("Unexpectedly succeeded")

    def do_test(self):
        self.blockdev_mirror()


def run(test, params, env):
    """
    Do block mirror from source node to source node

    test steps:
        1. boot VM
        2. do block-mirror from source node to source node,i.e.
           both source node and target node are the same
        3. check error message

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorSameSrcTgt(test, params, env)
    mirror_test.run_test()
