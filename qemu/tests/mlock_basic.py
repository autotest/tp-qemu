import logging
from resource import getpagesize

from virttest import env_process, error_context
from virttest.staging.utils_memory import read_from_vmstat

LOG_JOB = logging.getLogger("avocado.test")


class MlockBasic(object):
    """
    Base class for mlock test
    """

    def __init__(self, test, params, env):
        self.test = test
        self.params = params
        self.env = env
        self.realtime_mlock = params["realtime_mlock"]
        self.vm_mem = int(params["mem"])
        self.vm = None
        self.mlock_pre = None
        self.mlock_post = None
        self.unevictable_pre = None
        self.unevictable_post = None

    def _check_mlock_unevictable(self):
        """
        Check nr_mlock and nr_unevictable with guest memory
        """
        if self.realtime_mlock == "on":
            vm_pages = self.vm_mem * 1024 * 1024 / getpagesize()
            nr_mlock = self.mlock_post - self.mlock_pre
            nr_unevictable = self.unevictable_post - self.unevictable_pre
            if nr_mlock < vm_pages:
                self.test.fail(
                    "nr_mlock is not fit with VM memory"
                    " when mlock is %s!"
                    " nr_mlock = %d, vm_mem = %d."
                    % (self.realtime_mlock, nr_mlock, self.vm_mem)
                )
            if nr_unevictable < vm_pages:
                self.test.fail(
                    "nr_unevictable is not fit with VM memory"
                    " when mlock is %s!"
                    " nr_unevictable = %d, vm_mem = %d."
                    % (self.realtime_mlock, nr_unevictable, self.vm_mem)
                )
        else:
            if self.mlock_post != self.mlock_pre:
                self.test.fail(
                    "mlock_post != mlock_pre when mlock is %s!" % self.realtime_mlock
                )
            if self.unevictable_post != self.unevictable_pre:
                self.test.fail(
                    "unevictable_post != unevictable_pre"
                    " when mlock is %s!" % self.realtime_mlock
                )

    def start(self):
        """
        Start mlock basic test
        """
        error_context.context(
            "Get nr_mlock and nr_unevictable in host" " before VM start!", LOG_JOB.info
        )
        self.mlock_pre = read_from_vmstat("nr_mlock")
        self.unevictable_pre = read_from_vmstat("nr_unevictable")
        LOG_JOB.info(
            "mlock_pre is %d and unevictable_pre is %d.",
            self.mlock_pre,
            self.unevictable_pre,
        )
        self.params["start_vm"] = "yes"

        error_context.context("Starting VM!", LOG_JOB.info)
        env_process.preprocess_vm(
            self.test, self.params, self.env, self.params["main_vm"]
        )
        self.vm = self.env.get_vm(self.params["main_vm"])
        self.vm.verify_alive()

        error_context.context(
            "Get nr_mlock and nr_unevictable in host" " after VM start!", LOG_JOB.info
        )
        self.mlock_post = read_from_vmstat("nr_mlock")
        self.unevictable_post = read_from_vmstat("nr_unevictable")
        LOG_JOB.info(
            "mlock_post is %d and unevictable_post is %d.",
            self.mlock_post,
            self.unevictable_post,
        )

        self._check_mlock_unevictable()


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
    mlock_test = MlockBasic(test, params, env)
    mlock_test.start()

    error_context.context("Check kernel crash message!", test.log.info)
    mlock_test.vm.verify_kernel_crash()
