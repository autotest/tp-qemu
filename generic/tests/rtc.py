from virttest import error_context

from generic.tests.monotonic_time import TimeClientTest


class RtcTest(TimeClientTest):
    def __init__(self, test, params, env, test_name, rtc_path):
        super(RtcTest, self).__init__(test, params, env, test_name)
        self.def_rtc = rtc_path
        self.maxfreq = 64

    def _test(self):
        if self.session.cmd_status("ls %s" % self.def_rtc):
            self.test.cancel("RTC device %s does not exist" % self.def_rtc)
        (exit_status, output) = self.session.cmd_status_output(
            "cd %s && ./rtctest %s %s" % (self.src_dir, self.def_rtc, self.maxfreq),
            timeout=240,
        )
        if exit_status != 0:
            self.test.fail("Test fail on RTC device, output: %s" % output)

    def test_RTC(self):
        self._test()


@error_context.context_aware
def run(test, params, env):
    """
    A simple test of realtime clock driver, does the functional test of
    interrupt, alarm and requested frequency.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    rtc_test = RtcTest(test, params, env, "rtc", "/dev/rtc0")
    rtc_test.setUp()
    rtc_test.runTest()
    rtc_test.cleanUp()
