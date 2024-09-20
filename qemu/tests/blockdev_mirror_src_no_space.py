from provider.blockdev_mirror_parallel import BlockdevMirrorParallelTest
from provider.job_utils import get_event_by_condition


class BlockdevMirrorSrcNoSpaceTest(BlockdevMirrorParallelTest):
    """
    Do blockdev-mirror from a source without enough space
    """

    def overflow_source(self):
        tag = self._source_images[0]
        dd_cmd = self.params["write_file_cmd"] % self.disks_info[tag][1]
        self._session.cmd(dd_cmd, ignore_all_errors=True)
        self._session.close()

    def check_io_error_event(self):
        event = get_event_by_condition(
            self.main_vm, "BLOCK_IO_ERROR", self.params.get_numeric("event_timeout", 30)
        )

        if event:
            if event["data"].get("reason") != self.params["error_msg"]:
                self.test.fail("Unexpected error")
        else:
            self.test.fail("Failed to get BLOCK_IO_ERROR event")

    def do_test(self):
        self._session = self.main_vm.wait_for_login()
        self.blockdev_mirror()
        self.check_io_error_event()


def run(test, params, env):
    """
    Do blockdev-mirror from a source without enough space

    test steps:
        1. boot VM with 2G data disk(actual size: 100M)
        2. format the data disk and mount it
        3. create a file
        4. add a local fs image for mirror to VM via qmp commands
        5. dd file to data disk and do blockdev-mirror in parallel
        6. BLOCK_IO_ERROR event should be received, and mirror job
           should be completed

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorSrcNoSpaceTest(test, params, env)
    mirror_test.run_test()
