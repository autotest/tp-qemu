import random
import time

from qemu.tests import blk_commit


class BlockCommitReboot(blk_commit.BlockCommit):
    def reboot(self):
        """
        Reset guest with system_reset;
        """
        return super(BlockCommitReboot, self).reboot(boot_check=False)

    def action_when_start(self):
        """
        start pre-action in new threads;
        """
        super(BlockCommitReboot, self).action_when_start()
        self.test.log.info(
            "sleep for random time between 0 to 20, to perform "
            "the block job during different stage of rebooting"
        )
        time.sleep(random.randint(0, 20))


def run(test, params, env):
    """
    block_commit_reboot test:
    1). boot a guest, then reboot the guest with system_reset;
    2). create snapshots and start commit job immediately;
    3). waiting commit done and check guest is alive;

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    reboot_test = BlockCommitReboot(test, params, env, tag)
    try:
        reboot_test.action_when_start()
        reboot_test.create_snapshots()
        reboot_test.start()
        reboot_test.action_after_finished()
    finally:
        try:
            reboot_test.clean()
        except Exception as e:
            test.log.warning(e)
