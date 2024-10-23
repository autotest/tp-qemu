import logging
import os
from inspect import ismethod

from virttest import data_dir, error_context

LOG_JOB = logging.getLogger("avocado.test")


class TimeClientTest(object):
    def __init__(self, test, params, env, test_name):
        self.test = test
        self.vm = env.get_vm(params["main_vm"])
        self.session = self.vm.wait_for_login()
        self.host_dir = os.path.join(data_dir.get_deps_dir(), test_name)
        self.src_dir = os.path.join("/tmp/", test_name)

    def setUp(self):
        LOG_JOB.info("Copy files to guest")
        self.vm.copy_files_to(self.host_dir, os.path.dirname(self.src_dir))
        self.session.cmd("cd %s && make clobber && make" % self.src_dir)

    def runTest(self):
        for attr in dir(self):
            if not attr.startswith("test_"):
                continue
            func = getattr(self, attr)
            if ismethod(func):
                func()

    def cleanUp(self):
        self.session.cmd("rm -rf %s" % self.src_dir)
        self.session.close()


class MonotonicTime(TimeClientTest):
    def _test(self, test_type=None, duration=300, threshold=None):
        """
        :params test_type: Test gettimeofday(), TSC or
                           clock_gettime(CLOCK_MONOTONIC).
        :params duration: Tests run for 'duration' seconds and check that
                          the selected time interface does not go backwards
                          by more than 'threshold'.
        :params threshold: Same resolution as clock source.
        """
        if not test_type:
            self.test.error("missing test type")
        LOG_JOB.info("Test type: %s", test_type)
        timeout = float(duration) + 100.0

        cmd = self.src_dir + "/time_test"
        cmd += " --duration " + str(duration)
        if threshold:
            cmd += " --threshold " + str(threshold)
        cmd += " " + test_type

        (exit_status, stdout) = self.session.cmd_status_output(cmd, timeout=timeout)
        LOG_JOB.info("Time test command exit status: %s", exit_status)
        if exit_status != 0:
            for line in stdout.splitlines():
                if line.startswith("ERROR:"):
                    self.test.error(line)
                if line.startswith("FAIL:"):
                    self.test.fail(line)
            self.test.error("unknown test failure")

    def test_Gtod(self):
        self._test(test_type="gtod", threshold=0)

    def test_Tsc_lfence(self):
        self._test(test_type="tsc_lfence", threshold=0)

    def test_Clock(self):
        self._test(test_type="clock", threshold=0)


@error_context.context_aware
def run(test, params, env):
    """
    Check various time interfaces:
      gettimeofday()
      clock_gettime(CLOCK_MONTONIC)
      TSC
    for monotonicity.

    Based on time-warp-test.c by Ingo Molnar.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    monotonic_test = MonotonicTime(test, params, env, "monotonic_time")
    monotonic_test.setUp()
    monotonic_test.runTest()
    monotonic_test.cleanUp()
