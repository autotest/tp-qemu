import logging

from virttest import error_context

from qemu.tests import blk_stream

LOG_JOB = logging.getLogger("avocado.test")


class BlockStreamSimple(blk_stream.BlockStream):
    def __init__(self, test, params, env, tag):
        super(BlockStreamSimple, self).__init__(test, params, env, tag)

    @error_context.context_aware
    def query_status(self):
        """
        query running block streaming job info;
        """
        error_context.context("query job status", LOG_JOB.info)
        if not self.get_status():
            self.test.fail("No active job")


def run(test, params, env):
    """
    block_stream_simple test:
    1). launch block streaming job w/ max speed in param "default_speed"
        if defined by users or w/o max speed limit by default,
        to be noted, default_speed=0 means no limit in qemu side.
    2). reset max job speed before steady status(optional)
    3). cancel active job on the device(optional)

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    simple_test = BlockStreamSimple(test, params, env, tag)
    try:
        simple_test.action_before_start()
        simple_test.create_snapshots()
        simple_test.start()
        simple_test.action_when_streaming()
        simple_test.action_after_finished()
    finally:
        simple_test.clean()
