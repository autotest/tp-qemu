"""
Module specified for stream test cases that don't need to wait job done
"""

from avocado.utils import memory

from provider import backup_utils, blockdev_stream_base, job_utils


class BlockdevStreamNowaitTest(blockdev_stream_base.BlockDevStreamTest):
    """
    block-stream test module without waiting job done
    """

    def __init__(self, test, params, env):
        super(BlockdevStreamNowaitTest, self).__init__(test, params, env)
        self._job = None

    def blockdev_stream(self):
        """Run block-stream without waiting job completed"""
        self._job = backup_utils.blockdev_stream_nowait(
            self.main_vm, self._top_device, **self._stream_options
        )

    def wait_stream_job_completed(self):
        """Wait till the stream job completed"""
        try:
            job_utils.wait_until_block_job_completed(self.main_vm, self._job)
        finally:
            memory.drop_caches()
