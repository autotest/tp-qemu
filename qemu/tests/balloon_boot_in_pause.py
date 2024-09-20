import random

from avocado.core import exceptions
from virttest import error_context, utils_misc

from provider import win_driver_utils
from qemu.tests.balloon_check import BallooningTest


class BallooningTestPause(BallooningTest):
    """
    Basic functions of memory ballooning test for guest booted
    in paused status
    """

    def __init__(self, test, params, env):
        super(BallooningTestPause, self).__init__(test, params, env)

        self.vm = env.get_vm(params["main_vm"])
        # ori_mem is the original memory
        # pre_mem/gmem is the memory value before balloon test
        self.ori_mem = self.get_vm_mem(self.vm)
        if self.get_ballooned_memory() != self.ori_mem:
            self.balloon_memory(self.ori_mem)
        self.pre_mem = self.ori_mem
        self.pre_gmem = None

    @error_context.context_aware
    def memory_check(self, step, changed_mem):
        """
        Check memory change status in monitor and return memory both
        in guest and monitor
        :param step: the check point string
        :type step: string
        :param changed_mem: ballooned memory in current step(compared with
        last round of memory, i.e. self.pre_mem, instead of self.ori_mem)
        :type changed_mem: int
        :return: memory size get from monitor and guest
        :rtype: tuple
        """
        error_context.context("Check memory status %s" % step, self.test.log.info)
        mmem = self.get_ballooned_memory()
        gmem = self.get_memory_status()
        if self.pre_gmem:
            # for rhel guest, the gmem is total memory in guest;
            # for windows guest, the gmem is used memory in guest.
            if self.params["os_type"] == "windows":
                guest_ballooned_mem = self.pre_gmem - gmem
            else:
                guest_ballooned_mem = gmem - self.pre_gmem
        if (mmem - self.pre_mem) != changed_mem or (
            self.pre_gmem and abs(guest_ballooned_mem - changed_mem) > 100  # pylint: disable=E0606
        ):
            self.error_report(step, self.pre_mem + changed_mem, mmem, gmem)
            self.test.fail("Balloon test failed %s" % step)
        return (mmem, gmem)

    @error_context.context_aware
    def balloon_memory(self, new_mem):
        """
        Baloon guest memory to new_mem

        :param new_mem: New desired memory.
        :type new_mem: int
        """
        error_context.context("Change VM memory to %s" % new_mem, self.test.log.info)
        try:
            self.vm.balloon(new_mem)
        except Exception as e:
            if self.vm.monitor.verify_status("paused"):
                # Make sure memory not changed before the guest resumed
                if self.get_ballooned_memory() != self.pre_mem:
                    self.test.fail("Memory changed before guest resumed")

                self.test.log.info("Resume the guest")
                self.vm.resume()
            elif new_mem == self.get_ballooned_memory():
                pass
            else:
                self.test.fail("Balloon memory fail with error message:%s" % e)
        compare_mem = new_mem
        balloon_timeout = float(self.params.get("balloon_timeout", 240))
        status = utils_misc.wait_for(
            (lambda: compare_mem == self.get_ballooned_memory()), balloon_timeout
        )
        if status is None:
            self.test.fail(
                "Failed to balloon memory to expect value during "
                "%ss" % balloon_timeout
            )

    def get_memory_boundary(self):
        """
        Get the legal memory boundary for the balloon test

        :return: min and max size of the memory
        :rtype: tuple
        """
        if self.ori_mem <= (1 * 1024 * 1024):
            ratio = float(self.params.get("ratio_1", 0.8))
        else:
            ratio = float(self.params.get("ratio_2", 0.5))
        min_size = int(ratio * self.ori_mem)
        max_size = self.ori_mem
        return (min_size, max_size)

    def error_report(self, step, expect_value, monitor_value, guest_value):
        """
        Generate the error report

        :param step: the step of the error happen
        :param expect_value: memory size assign to the vm
        :param monitor_value: memory size report from monitor
        :param guest_value: memory size report from guest
        """
        self.test.log.error("Memory size mismatch %s:\n", step)
        error_msg = "Wanted to be changed: %s\n" % (expect_value - self.pre_mem)
        error_msg += "Changed in monitor: %s\n" % (monitor_value - self.pre_mem)
        if self.pre_gmem:
            error_msg += "Changed in guest: %s\n" % (guest_value - self.pre_gmem)
        self.test.log.error(error_msg)


class BallooningTestPauseWin(BallooningTestPause):
    """
    Windows memory ballooning test for guest booted in paused status
    """

    def get_memory_status(self):
        """
        Get Memory status inside guest

        :return: the used memory size inside guest.
        :rtype: int
        """
        return int(self.get_used_mem())


class BallooningTestPauseLinux(BallooningTestPause):
    """
    Linux memory ballooning test for guest booted in paused status
    """

    def get_memory_status(self):
        """
        Get Memory status inside guest

        :return: the total memory size inside guest.
        :rtype: int
        """
        return int(self.get_total_mem())


@error_context.context_aware
def run(test, params, env):
    """
    Balloon guest memory when guest started in paused status,
    use M when compare memory in this script:
    1) Boot a guest with balloon enabled and in paused status,
    i.e. '-S' used but not cont
    2) Evict guest memory in paused status, cont the guest;
    check memory in monitor
    3) To check if the guest memory balloon working well after above test,
    continue to do:
    3.1) Enlarge guest memory in running status;
    check memory both in guest and monitor
    3.2) Evict guest memory in running status;
    check memory both in guest and monitor
    4) Run subtest if necessary
    5) Reset memory back to the original value

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def _memory_check_after_sub_test():
        """
        Check memory status after subtest, the changed_mem is 0
        """
        try:
            return balloon_test.memory_check("after subtest", 0)
        except exceptions.TestFail:
            return None

    if params["os_type"] == "windows":
        balloon_test = BallooningTestPauseWin(test, params, env)
    else:
        balloon_test = BallooningTestPauseLinux(test, params, env)

    min_sz, max_sz = balloon_test.get_memory_boundary()

    for tag in params.objects("test_tags"):
        vm = env.get_vm(params["main_vm"])
        if vm.monitor.verify_status("paused"):
            error_context.context(
                "Running balloon %s test when" " the guest in paused status" % tag,
                test.log.info,
            )
        else:
            error_context.context(
                "Running balloon %s test after"
                " the guest turned to running status" % tag,
                test.log.info,
            )
        params_tag = params.object_params(tag)
        balloon_type = params_tag["balloon_type"]
        if balloon_type == "evict":
            expect_mem = int(random.uniform(min_sz, balloon_test.pre_mem))
        else:
            expect_mem = int(random.uniform(balloon_test.pre_mem, max_sz))
        balloon_test.balloon_memory(expect_mem)
        changed_memory = expect_mem - balloon_test.pre_mem
        mmem, gmem = balloon_test.memory_check("after %s memory" % tag, changed_memory)
        balloon_test.pre_mem = mmem
        balloon_test.pre_gmem = gmem

    subtest = params.get("sub_test_after_balloon")
    if subtest:
        error_context.context("Running subtest after guest balloon test", test.log.info)
        qemu_should_quit = balloon_test.run_balloon_sub_test(test, params, env, subtest)
        if qemu_should_quit == 1:
            return

        sleep_before_check = int(params.get("sleep_before_check", 0))
        timeout = int(params.get("balloon_timeout", 100)) + sleep_before_check
        msg = "Wait memory balloon back after %s " % subtest
        output = utils_misc.wait_for(
            _memory_check_after_sub_test, timeout, sleep_before_check, 5, msg
        )
        if output is None:
            test.fail(
                "Check memory status failed after subtest " "after %s seconds" % timeout
            )

    error_context.context(
        "Reset guest memory to original one after all the " "test", test.log.info
    )
    balloon_test.reset_memory()
    # for windows guest, disable/uninstall driver to get memory leak based on
    # driver verifier is enabled
    if params.get("os_type") == "windows":
        win_driver_utils.memory_leak_check(vm, test, params)
