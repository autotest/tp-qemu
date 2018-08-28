import re
import time
import logging

from avocado.utils import process
from virttest import env_process
from virttest import test_setup
from virttest import error_context

from generic.tests.guest_suspend import GuestSuspendBaseTest


class TimedriftTest(object):

    """
    Base class for time drift test, include common steps for time drift test;
    """

    def __init__(self, test, params, env):
        self.netdst = None
        self.test = test
        self.params = params
        self.env = env
        self.open_sessions = []

    def get_session(self, vm):
        timeout = float(self.params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=timeout)
        self.open_sessions.append(session)
        return session

    def setup_private_network(self):
        """
        Setup private network to avoid guest update clock via net;
        """
        logging.info("Setup private bridge 'atbr0' before test")
        self.params["nics"] = "nic1"
        self.params["netdst"] = "atbr0"
        nic_params = self.params.object_params("nic1")
        atbr = test_setup.PrivateBridgeConfig(nic_params)
        atbr.setup()
        self.netdst = atbr

    def cleanup_private_network(self):
        """
        cleanup private network in the end of test;
        """
        if self.netdst:
            logging.info("Clear private bridge after test")
            self.netdst.cleanup()
        return None

    def get_vm(self, create=False):
        """
        Get a live vm, if not create it;

        :param create: recreate VM or get a live VM.
        :return: Qemu vm object;
        """
        vm_name = self.params["main_vm"]
        if create:
            params = self.params
            params["start_vm"] = "yes"
            env_process.preprocess_vm(self.test, params, self.env, vm_name)
        vm = self.env.get_vm(vm_name)
        vm.verify_alive()
        return vm

    def close_sessions(self):
        """
        Close useless session at the end of test.
        """
        logging.info("Close useless session after test")
        open_sessions = [s for s in self.open_sessions if s]
        for session in open_sessions:
            session.close()

    def execute(self, cmd, session=None):
        """
        Execute command in guest or host, if session is not None return
        command output in guest else return command ouput in host;

        :param cmd: shell commands;
        :param session: ShellSession or None;
        :return: command output string
        :rtype: str
        """
        if session:
            timeout = int(self.params.get("execute_timeout", 360))
            ret = session.cmd_output(cmd, timeout=timeout)
        else:
            ret = process.system_output(cmd, shell=True)
        target = session and "guest" or "host"
        logging.debug("(%s) Execute command('%s')" % (target, cmd))
        return ret

    @error_context.context_aware
    def sync_host_time(self):
        """
        calibrate system time via ntp server, if session is not None,
        calibrate guest time else calibrate host time;

        :param session: ShellSession object or None
        :return: ntpdate command output;
        :rtype: str
        """
        error_context.context("Sync host time from ntp server", logging.info)
        cmd = self.params["sync_host_time_cmd"]
        return self.execute(cmd, None)

    def get_epoch_seconds(self, session):
        """
        Get epoch seconds from host and guest;
        """
        regex = r"epoch:\s+(\d+)"
        host_epoch_time_cmd = self.params["host_epoch_time_cmd"]
        guest_epoch_time_cmd = self.params["guest_epoch_time_cmd"]
        try:
            guest_timestr = session.cmd_output(
                guest_epoch_time_cmd,
                timeout=240)
            host_timestr = process.system_output(host_epoch_time_cmd,
                                                 shell=True)
            epoch_host, epoch_guest = list(
                map(lambda x: re.findall(regex, x)[0],
                    [host_timestr, guest_timestr]))
        except IndexError:
            logging.debug("Host Time: %s," % guest_timestr +
                          "Guest Time: %s" % guest_timestr)
        return list(map(float, [epoch_host, epoch_guest]))

    @error_context.context_aware
    def verify_clock_source(self, session):
        """
        Verify guest used expected clocksource;

        :param session: ShellSession object;
        :raise: error.TestFail Exception
        """
        error_context.context("Verify guest clock resource", logging.info)
        read_clock_source_cmd = self.params["read_clock_source_cmd"]
        real_clock_source = session.cmd_output(read_clock_source_cmd)
        expect_clock_source = self.params["clock_source"]
        if expect_clock_source not in real_clock_source:
            self.test.fail("Expect clock source: " +
                           expect_clock_source +
                           "Real clock source: %s" % real_clock_source)

    @error_context.context_aware
    def cleanup(self):
        error_context.context("Cleanup after test", logging.info)
        self.close_sessions()
        self.cleanup_private_network()


class BackwardtimeTest(TimedriftTest):

    """
    Base class for test time drift after backward host/guest system clock;
    """

    def __init__(self, test, params, env):
        super(BackwardtimeTest, self).__init__(test, params, env)

    @error_context.context_aware
    def set_time(self, nsec, session=None):
        """
        Change host/guest time, if session is not None, backword guest time,
        else backword host time;

        :param nsec: seconds to forward;
        :param session: ShellSession object;
        """
        target = session and "guest" or "host"
        step = "Forward %s time %s seconds" % (target, nsec)
        error_context.context(step, logging.info)
        cmd = self.params.get("set_%s_time_cmd" % target)
        return self.execute(cmd, session)

    @error_context.context_aware
    def check_drift_after_adjust_time(self, session):
        """
        Verify host/guest system/hardware clock drift after change
        host/guest time;

        :param session: ShellSession
        :raise: error.TestFail Exception
        """
        target = self.params.get("set_host_time_cmd") and "host" or "guest"
        step_info = "Check time difference between host and guest"
        step_info += " after forward %s time" % target
        error_context.context(step_info, logging.info)
        tolerance = float(self.params["tolerance"])
        timeout = float(self.params.get("workaround_timeout", 1.0))
        expect_difference = float(self.params["time_difference"])
        start_time = time.time()
        while time.time() < start_time + timeout:
            host_epoch_time, guest_epoch_time = self.get_epoch_seconds(session)
            real_difference = abs(host_epoch_time - guest_epoch_time)
            if abs(real_difference - expect_difference) < tolerance:
                return
        logging.info("Host epoch time: %s" % host_epoch_time)
        logging.info("Guest epoch time: %s" % guest_epoch_time)
        err_msg = "Unexcept time difference between host and guest after"
        err_msg += " testing.(actual difference: %s)" % real_difference
        err_msg += " except difference: %s)" % expect_difference
        self.test.fail(err_msg)

    @error_context.context_aware
    def check_dirft_before_adjust_time(self, session):
        """
        Verify host/guest system/hardware clock drift before change
        host/guest time;

        :param session: ShellSession
        :raise: error.TestFail Exception
        """
        target = self.params.get("set_host_time_cmd") and "host" or "guest"
        step_info = "Check time difference between host and guest"
        step_info += " before forward %s time" % target
        error_context.context(step_info, logging.info)
        tolerance = float(self.params.get("tolerance", 6))
        host_epoch_time, guest_epoch_time = self.get_epoch_seconds(session)
        real_difference = abs(host_epoch_time - guest_epoch_time)
        if real_difference > tolerance:
            logging.info("Host epoch time: %s" % host_epoch_time)
            logging.info("Guest epoch time: %s" % guest_epoch_time)
            err_msg = "Unexcept time difference (%s) " % real_difference
            err_msg += " between host and guest before testing."
            self.test.fail(err_msg)

    def pre_test(self):
        """
        TODO:
            step 1: setup private bridge network environment;
            step 2: sync host time from ntp server;
            step 3: verify system time drift between host and guest;
            step 4: verify guest clock source if linux guest;
        """
        self.setup_private_network()
        self.sync_host_time()
        vm = self.get_vm(create=True)
        session = self.get_session(vm)
        self.check_dirft_before_adjust_time(session)
        if self.params.get("read_clock_source_cmd"):
            self.verify_clock_source(session)

    def post_test(self):
        """
        TODO:
            step 7: verify system time drift between host and guest;
            step 8: close opening session and calibrate host time;
        Notes:
            Hardware clock time drift will not be check as it's a know issue;
        """
        vm = self.get_vm()
        session = self.get_session(vm)
        self.check_drift_after_adjust_time(session)
        self.sync_host_time()

    def run(self, fuc):
        self.pre_test()
        if callable(fuc):
            fuc()
        self.post_test()
        self.cleanup()


@error_context.context_aware
def run(test, params, env):
    """
    Time drift after change host/guest sysclock test:

    Include sub test:
       1): reboot guest after change host/guest system clock
       2): pause guest change host system clock and wait a long time, then
       cont guest;
       3): suspend guest change host system clock and wait a long time, then
       Resume guest;

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    class TestReboot(BackwardtimeTest):

        """
        Test Steps:
            5) Forward host/guest system time 30 mins
            6) Reboot guest
        """

        def __init__(self, test, params, env):
            super(TestReboot, self).__init__(test, params, env)

        @error_context.context_aware
        def reboot(self):
            vm = self.get_vm()
            session = self.get_session(vm)
            seconds_to_forward = int(self.params.get("seconds_to_forward", 0))
            if self.params.get("set_host_time_cmd"):
                self.set_time(seconds_to_forward)
            if self.params.get("set_guest_time_cmd"):
                self.set_time(seconds_to_forward, session=session)
            error_context.context("Reboot guest", logging.info)
            vm.reboot(session=session, method="shell")

        def run(self):
            fuc = self.reboot
            return super(TestReboot, self).run(fuc)

    class TestPauseresume(BackwardtimeTest):

        """
        Test Steps:
            5) Forward host system time 30mins
            6) Pause guest 30 mins, then cont it;
        """

        def __init__(self, test, params, env):
            super(TestPauseresume, self).__init__(test, params, env)

        @error_context.context_aware
        def pause_resume(self):
            vm = self.get_vm()
            sleep_seconds = float(params.get("sleep_seconds", 1800))
            error_context.context("Pause guest %s seconds" % sleep_seconds,
                                  logging.info)
            vm.pause()
            seconds_to_forward = int(self.params.get("seconds_to_forward", 0))
            if seconds_to_forward:
                self.set_time(seconds_to_forward)
            time.sleep(sleep_seconds)
            error_context.context("Resume guest", logging.info)
            vm.resume()

        def run(self):
            fuc = self.pause_resume
            return super(TestPauseresume, self).run(fuc)

    class TestSuspendresume(BackwardtimeTest, GuestSuspendBaseTest):

        """
        Test Steps:
            5) Suspend guest 30 mins, then resume it;
            6) Forward host system time 30mins
        """

        def __init__(self, test, params, env):
            BackwardtimeTest.__init__(self, test, params, env)

        def get_session(self, vm):
            timeout = float(self.params.get("login_timeout", 360))
            session = vm.wait_for_login(timeout=timeout)
            self.open_sessions.append(session)
            return session

        def _get_session(self):
            vm = self.get_vm()
            timeout = float(self.params.get("login_timeout", 360))
            if self.params["os_type"] == "windows":
                session = vm.wait_for_login(timeout=timeout)
            else:
                session = vm.wait_for_serial_login(timeout=timeout)
            self.open_sessions.append(session)
            return session

        @error_context.context_aware
        def action_during_suspend(self, **args):
            sleep_seconds = float(self.params.get("sleep_seconds", 1800))
            error_context.context("Sleep %s seconds before resume" %
                                  sleep_seconds, logging.info)
            seconds_to_forward = int(self.params.get("seconds_to_forward", 0))
            if seconds_to_forward:
                self.set_time(seconds_to_forward)
            time.sleep(sleep_seconds)

        def suspend_resume(self):
            vm = self.get_vm()
            GuestSuspendBaseTest.__init__(self, test, params, vm)
            if self.params.get("guest_suspend_type") == "mem":
                self.guest_suspend_mem(self.params)
            else:
                self.guest_suspend_disk(self.params)

        def run(self):
            fuc = self.suspend_resume
            return super(TestSuspendresume, self).run(fuc)

    vm_action = params["vm_action"].replace("_", "")
    vm_action = vm_action.capitalize()
    test_name = "Test%s" % vm_action
    SubTest = locals().get(test_name)
    if issubclass(SubTest, BackwardtimeTest):
        timedrift_test = SubTest(test, params, env)
        timedrift_test.run()
