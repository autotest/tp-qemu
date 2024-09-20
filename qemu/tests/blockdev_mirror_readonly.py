import re

from aexpect import ShellCmdError

from provider.blockdev_mirror_wait import BlockdevMirrorWaitTest


class BlockdevMirrorReadonlyDeviceTest(BlockdevMirrorWaitTest):
    """
    Block mirror on readonly device test
    """

    def prepare_test(self):
        self.prepare_main_vm()
        self.add_target_data_disks()

    def check_mirrored_block_nodes_readonly(self):
        for tag in self.params.objects("source_images"):
            try:
                self.format_data_disk(tag)
            except ShellCmdError as e:
                if not re.search(self.params["error_msg"], str(e), re.M):
                    self.test.fail("Unexpected disk format error: %s" % str(e))
            else:
                self.test.fail("Unexpected disk format success")

    def do_test(self):
        self.blockdev_mirror()
        self.check_mirrored_block_nodes_attached()
        self.check_mirrored_block_nodes_readonly()


def run(test, params, env):
    """
     Block mirror on readonly device test

    test steps:
        1. boot VM with a 2G data disk(readonly=on)
        2. add a target disk for mirror to VM via qmp commands
        3. do full block-mirror
        4. check the mirror disk is attached
        5. check the mirror disk is readonly

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorReadonlyDeviceTest(test, params, env)
    mirror_test.run_test()
