from provider import job_utils
from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest


class BlockdevMirrorNospaceTest(BlockdevMirrorNowaitTest):
    """Mirror to an image without enough space"""

    def post_test(self):
        """Neither need to remove image nor to stop vm"""
        pass

    def check_no_space_error(self):
        tmo = self.params.get_numeric("block_io_error_timeout", 60)

        # check 'error' message in BLOCK_JOB_COMPLETED event
        cond = {"device": self._jobs[0]}
        event = job_utils.get_event_by_condition(
            self.main_vm, job_utils.BLOCK_JOB_COMPLETED_EVENT, tmo, **cond
        )
        if event:
            if event["data"].get("error") != self.params["error_msg"]:
                self.test.fail("Unexpected error: %s" % event["data"].get("error"))
        else:
            self.test.fail(
                "Failed to get BLOCK_JOB_COMPLETED event for %s" % self._jobs[0]
            )

    def do_test(self):
        self.blockdev_mirror()
        self.check_no_space_error()


def run(test, params, env):
    """
    Do blockdev-mirror to an image without enough space
    test steps:
        1. boot VM
        2. add a 100M image for system image mirror
        3. do blockdev-mirror for system image
        4. check no space error
    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorNospaceTest(test, params, env)
    mirror_test.run_test()
