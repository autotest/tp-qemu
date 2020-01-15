from virttest import error_context

from provider.blockdev_stream_base import BlockDevStreamTest


@error_context.context_aware
def run(test, params, env):
    """
    Test VM block device stream feature
    1) Start VM with a data disk
    2) create file in data disk and save it's md5sum
    3) Create snapshot for the data disk
    4) Save a temp file and record md5sum
    5) stream the data disk
    6) Verify files' md5sum

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.

    """
    stream_test = BlockDevStreamTest(test, params, env)
    stream_test.run_test()
