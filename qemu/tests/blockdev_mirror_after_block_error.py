from provider.blockdev_mirror_wait import BlockdevMirrorWaitTest
from provider.job_utils import get_event_by_condition


class BlockdevMirrorAfterBlockErrorTest(BlockdevMirrorWaitTest):
    """
    Do blockdev-mirror after block error
    """

    def overflow_source_image(self):
        session = self.main_vm.wait_for_login()
        tag = self._source_images[0]
        dd_cmd = self.params["write_file_cmd"] % self.disks_info[tag][1]
        session.cmd(dd_cmd, ignore_all_errors=True)
        session.close()

    def wait_block_io_error(self):
        event = get_event_by_condition(
            self.main_vm, "BLOCK_IO_ERROR", self.params.get_numeric("event_timeout", 30)
        )
        if event is None:
            self.test.fail("Failed to get BLOCK_IO_ERROR event")

    def do_test(self):
        self.overflow_source_image()
        self.wait_block_io_error()
        self.blockdev_mirror()
        self.check_mirrored_block_nodes_attached()


def run(test, params, env):
    """
    Do blockdev-mirror after block error

    test steps:
        1. boot VM with 2G data disk(actual size: 100M)
        2. format the data disk and mount it
        3. create a file
        4. add a local fs image for mirror to VM via qmp commands
        5. dd a file(file size > sizeof data disk) to data disk
        6. wait till BLOCK_IO_ERROR occurred
        7. do blockdev-mirror, it works fine

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorAfterBlockErrorTest(test, params, env)
    mirror_test.run_test()
