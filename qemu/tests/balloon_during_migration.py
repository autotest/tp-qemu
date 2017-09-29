import random
import logging

from virttest import utils_misc
from virttest import error_context
from qemu.tests.balloon_check import BallooningTestWin


@error_context.context_aware
def run(test, params, env):
    """
    KVM balloon during migration test:
    1) Boot up src guest in background
    2) Keep running balloon test
    3) Send a migration command to the source VM and wait until it's finished.
    4) Kill off the source VM.
    5) Log into the destination VM after the migration is finished.

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    login_timeout = int(params.get("login_timeout", 360))
    session = vm.wait_for_login(timeout=login_timeout)

    balloon_test = BallooningTestWin(test, params, env)
    min_sz, max_sz = balloon_test.get_memory_boundary()
    bg = utils_misc.InterruptedThread(vm.migrate, )
    error_context.context("Start migration background ...", logging.info)
    bg.start()

    try:
        while bg.isAlive():
            balloon_test.balloon_memory(int(random.uniform(min_sz, max_sz)))
    except Exception, err:
        test.fail("Balloon test failed: %s" % err)
    finally:
        bg.join()
        session.close()
