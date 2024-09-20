from provider import job_utils
from provider.blockdev_stream_nowait import BlockdevStreamNowaitTest


class BlockdevStreamNospaceTest(BlockdevStreamNowaitTest):
    """
    Block stream(on-error: report) to an image without enough space
    """

    def post_test(self):
        """No need to remove image nor stop vm"""
        pass

    def check_no_space_error(self):
        tmo = self.params.get_numeric("block_io_error_timeout", 60)

        # check 'error' message in BLOCK_JOB_COMPLETED event
        cond = {"device": self._job}
        event = job_utils.get_event_by_condition(
            self.main_vm, job_utils.BLOCK_JOB_COMPLETED_EVENT, tmo, **cond
        )
        if event:
            if event["data"].get("error") != self.params["error_msg"]:
                self.test.fail("Unexpected error: %s" % event["data"].get("error"))
        else:
            self.test.fail("Failed to get BLOCK_JOB_COMPLETED event for %s" % self._job)

    def do_test(self):
        self.create_snapshot()
        self.blockdev_stream()
        self.check_no_space_error()


def run(test, params, env):
    """
     Do block-stream(on-error: report) to an image without enough space
    test steps:
        1. boot VM
        2. add a 100M snapshot image for system image
        3. take snapshot for system image
        4. do block-stream for system image(on-error: report)
        5. check no space error
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamNospaceTest(test, params, env)
    stream_test.run_test()
