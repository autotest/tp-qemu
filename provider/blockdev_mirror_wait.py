"""
Module specified for non-parallel test cases that need to wait job done,
please refer to blockdev_mirror_base for detailed test strategy.
"""

from avocado.utils import memory

from provider import backup_utils, blockdev_mirror_base


class BlockdevMirrorWaitTest(blockdev_mirror_base.BlockdevMirrorBaseTest):
    """
    block-mirror test module, waiting mirror job done
    """

    def blockdev_mirror(self):
        """Run block-mirror and wait job done"""
        try:
            for idx, source_node in enumerate(self._source_nodes):
                backup_utils.blockdev_mirror(
                    self.main_vm,
                    source_node,
                    self._target_nodes[idx],
                    **self._backup_options[idx],
                )
        finally:
            memory.drop_caches()
