from provider import job_utils
from provider.blockdev_stream_nowait import BlockdevStreamNowaitTest


class BlockdevStreamNoBacking(BlockdevStreamNowaitTest):
    """Do block-stream to an image without backing"""

    def pre_test(self):
        """vm will be started by VT, and no image will be created"""
        pass

    def post_test(self):
        """vm will be stopped by VT, and no image will be removed"""
        pass

    def verify_job_status(self):
        tmo = self.params.get_numeric("job_completed_timeout", 30)

        # check offset/len in BLOCK_JOB_COMPLETED event
        cond = {"device": self._job}
        event = job_utils.get_event_by_condition(
            self.main_vm, job_utils.BLOCK_JOB_COMPLETED_EVENT, tmo, **cond
        )
        if event:
            if event["data"].get("offset") != 0 or event["data"].get("len") != 0:
                self.test.fail("offset and len should always be 0")
        else:
            self.test.fail("Failed to get BLOCK_JOB_COMPLETED event for %s" % self._job)

    def do_test(self):
        self.blockdev_stream()
        self.verify_job_status()


def run(test, params, env):
    """
    Do block-stream to an image without backing

    test steps:
        1. boot VM
        2. do block-stream to the system image(without backing)
        3. check job completed and both len and offset should be 0
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    stream_test = BlockdevStreamNoBacking(test, params, env)
    stream_test.run_test()
