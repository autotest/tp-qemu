import logging

from virttest import error_context

from qemu.tests import blk_stream

LOG_JOB = logging.getLogger("avocado.test")


class BlockStreamNegative(blk_stream.BlockStream):
    def __init__(self, test, params, env, tag):
        super(BlockStreamNegative, self).__init__(test, params, env, tag)

    @error_context.context_aware
    def set_speed(self):
        """
        set limited speed for block job;
        """
        params = self.parser_test_args()
        match_str = params.get("match_str", "Invalid parameter type")
        default_speed = int(params.get("default_speed"))
        expected_speed = params.get("expected_speed", default_speed)
        if params.get("need_convert_to_int", "no") == "yes":
            expected_speed = int(expected_speed)
        error_context.context("set speed to %s B/s" % expected_speed, LOG_JOB.info)
        args = {"device": self.device, "speed": expected_speed}
        response = str(self.vm.monitor.cmd_qmp("block-job-set-speed", args))
        if "(core dump)" in response:
            self.test.fail("Qemu core dump when reset " "speed to a negative value.")
        if match_str not in response:
            self.test.fail(
                "Fail to get expected result. %s is expected in %s"
                % (match_str, response)
            )
        LOG_JOB.info("Keyword '%s' is found in QMP output '%s'.", match_str, response)


def run(test, params, env):
    """
    block_stream_negative test:
    1). launch block streaming job w/ speed in param "default_speed".
    2). reset speed to a negative value.
    3). check whether error is as expected:
        if yes, test continues going with "default_speed",
        else, test failed.

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    negative_test = BlockStreamNegative(test, params, env, tag)
    try:
        negative_test.create_snapshots()
        negative_test.start()
        negative_test.action_when_streaming()
        negative_test.action_after_finished()
    finally:
        negative_test.clean()
