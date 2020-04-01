from provider.blockdev_commit_base import BlockDevCommitTest


def run(test, params, env):
    """
    Block commit base Test

    1. boot guest with data disk
    2. create 4 snapshots and save file in each snapshot
    3. commit snapshot 3 to snapshot 4
    6. verify files's md5
    """

    block_test = BlockDevCommitTest(test, params, env)
    block_test.run_test()
