import logging
from resource import getpagesize

from avocado.utils import process

from virttest import env_process
from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    [Mlock] Basic test, this case will:
    1) Get nr_mlock and nr_unevictable in host before VM start.
    2) Start the VM.
    3) Get nr_mlock and nr_unevictable in host after VM start.
    4) Check nr_mlock and nr_unevictable with VM memory.
    5) Check kernel crash

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_mlock_unevictable(mlock_cmd, unevictable_cmd):
        """
        Get nr_mlock and nr_unevictable in host

        :param mlock_cmd: CMD to get nr_mlock
        :param unevictable_cmd: CMD to get nr_unevictable
        """
        mlock = int(process.system_output(mlock_cmd).split().pop())
        unevictable = int(process.system_output(unevictable_cmd).split().pop())
        return mlock, unevictable

    mlock_cmd = params["mlock_cmd"]
    unevictable_cmd = params["unevictable_cmd"]
    vm_mem = int(params["mem"])

    error_context.context("Get nr_mlock and nr_unevictable in host before VM start!", logging.info)
    mlock_pre, unevictable_pre = get_mlock_unevictable(mlock_cmd, unevictable_cmd)
    logging.info("mlock_pre is %d and unevictable_pre is %d.", mlock_pre, unevictable_pre)
    params["start_vm"] = "yes"

    error_context.context("Starting VM!", logging.info)
    env_process.preprocess_vm(test, params, env, params["main_vm"])
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()

    error_context.context("Get nr_mlock and nr_unevictable in host after VM start!", logging.info)
    mlock_post, unevictable_post = get_mlock_unevictable(mlock_cmd, unevictable_cmd)
    logging.info("mlock_post is %d and unevictable_post is %d.", mlock_post, unevictable_post)

    realtime_mlock = params["realtime_mlock"]
    if realtime_mlock == "on":
        nr_mlock = mlock_post - mlock_pre
        vm_pages = vm_mem * 1024 * 1024 / getpagesize()
        if nr_mlock < vm_pages:
            test.fail("nr_mlock is not fit with VM memory when mlock is %s! nr_mlock = %d, vm_mem = %d."
                      % (realtime_mlock, nr_mlock, vm_mem))
        nr_unevictable = unevictable_post - unevictable_pre
        if nr_unevictable < vm_pages:
            test.fail("nr_unevictable is not fit with VM memory when mlock is %s! nr_unevictable = %d, vm_mem = %d."
                      % (realtime_mlock, nr_unevictable, vm_mem))
    else:
        if mlock_post != mlock_pre:
            test.fail("mlock_post is not equal to mlock_pre when mlock is %s!" % realtime_mlock)
        if unevictable_post != unevictable_pre:
            test.fail("unevictable_post is not equal to unevictable_pre when mlock is %s!" % realtime_mlock)

    error_context.context("Check kernel crash message!", logging.info)
    vm.verify_kernel_crash()
