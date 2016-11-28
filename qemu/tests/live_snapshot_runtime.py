from autotest.client.shared import utils
from autotest.client.shared import error
from qemu.tests import live_snapshot_basic


class LiveSnapshotRuntime(live_snapshot_basic.LiveSnapshot):

    def __init__(self, test, params, env, tag):
        super(LiveSnapshotRuntime, self).__init__(test, params, env, tag)

    @error.context_aware
    def reboot(self):
        """
        Reset guest with system_reset;
        """
        method = self.params.get("reboot_method", "system_reset")
        return super(LiveSnapshotRuntime, self).reboot(method=method, boot_check=False)

    @error.context_aware
    def action_when_start(self):
        """
        start pre-action in new threads;
        do live snapshot during pre-action.
        """
        tag = self.params.get("source_image", "image1")
        for test in self.params.get("when_start").split():
            if hasattr(self, test):
                fun = getattr(self, test)
                bg = utils.InterruptedThread(fun)
                bg.start()
                if bg.isAlive():
                    self.create_snapshot()
                    bg.join()


def run(test, params, env):
    """
    live_snapshot runtime test:
    1). boot guest;
    2). do some operations, like reboot;
    3). create snapshots during the operations in step 2;
    4). waiting operations done and check guest is alive;

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    runtime_test = LiveSnapshotRuntime(test, params, env, tag)
    try:
        runtime_test.action_when_start()
        runtime_test.action_after_finished()
    finally:
        try:
            runtime_test.clean()
        except Exception:
            pass
