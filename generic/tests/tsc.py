import re

from virttest import error_context

from generic.tests.monotonic_time import TimeClientTest


class TscTest(TimeClientTest):
    def __init__(self, test, params, env, test_name):
        super(TscTest, self).__init__(test, params, env, test_name)
        self.args = "-t 650"

    def _test(self):
        cmd = self.src_dir + "/checktsc "
        cmd += self.args

        (exit_status, result) = self.session.cmd_status_output(cmd)

        if exit_status != 0:
            self.test.log.error("Program checktsc exit status is %s", exit_status)
            default_fail = "UNKNOWN FAILURE: rc=%d from %s" % (exit_status, cmd)

            if exit_status == 1:
                if result.strip("\n").endswith("FAIL"):
                    max_delta = 0
                    reason = ""
                    threshold = int(self.args.split()[1])
                    latencies = re.findall(r"CPU \d+ - CPU \d+ =\s+-*\d+", result)
                    for ln in latencies:
                        cur_delta = int(ln.split("=", 2)[1])
                        if abs(cur_delta) > max_delta:
                            max_delta = abs(cur_delta)
                            reason = ln
                    if max_delta > threshold:
                        reason = "Latency %s exceeds threshold %d" % (reason, threshold)
                        self.test.fail(reason)

            self.test.error(default_fail)

    def test_TSC(self):
        self._test()


@error_context.context_aware
def run(test, params, env):
    """
    Checktsc is a user space program that checks TSC synchronization
    between pairs of CPUs on an SMP system using a technique borrowed
    from the Linux 2.6.18 kernel.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    tsc_test = TscTest(test, params, env, params["tsc_test_name"])
    tsc_test.setUp()
    tsc_test.runTest()
    tsc_test.cleanUp()
