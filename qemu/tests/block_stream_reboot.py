import random
import time

from virttest import error_context

from qemu.tests import blk_stream


class BlockStreamReboot(blk_stream.BlockStream):
    @error_context.context_aware
    def reboot(self):
        """
        Reset guest with system_reset;
        """
        params = self.parser_test_args()
        method = params.get("reboot_method", "system_reset")
        super(BlockStreamReboot, self).reboot(method=method)
        time.sleep(random.randint(0, 20))


def run(test, params, env):
    """
    block_stream_reboot test:
    1). boot guest, then reboot guest with system_reset;
    2). create snapshots and start stream job immediately;
    3). waiting stream done and check guest is alive;

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    reboot_test = BlockStreamReboot(test, params, env, tag)
    try:
        reboot_test.action_before_start()
        reboot_test.create_snapshots()
        reboot_test.start()
        reboot_test.action_after_finished()
    finally:
        reboot_test.clean()
