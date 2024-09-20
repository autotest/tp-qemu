from provider.blockdev_mirror_parallel import BlockdevMirrorParallelTest


class BlockdevMirrorMultipleBlocksTest(BlockdevMirrorParallelTest):
    """do block-mirror for multiple disks in parallel"""

    pass


def run(test, params, env):
    """
    Multiple block mirror simultaneously

    test steps:
        1. boot VM with two 2G data disks
        2. format data disks and mount it
        3. create a file on both disks
        4. add target disks for mirror to VM via qmp commands
        4. do block-mirror for both disks in parallel
        5. check mirrored disks are attached
        6. restart VM with mirrored disks, check files and md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorMultipleBlocksTest(test, params, env)
    mirror_test.run_test()
