from provider.blockdev_mirror_wait import BlockdevMirrorWaitTest


class BlockdevMirrorRBDNode(BlockdevMirrorWaitTest):
    """
    Block mirror to rbd target
    """

    pass


def run(test, params, env):
    """
     Block mirror to rbd node

    test steps:
        1. boot VM with a 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a rbd target disk for mirror to VM via qmp commands
        5. do block-mirror to the rbd node
        6. check the mirror disk is attached
        7. restart vm with the mirror disk as its data disk
        8. check the file's md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorRBDNode(test, params, env)
    mirror_test.run_test()
