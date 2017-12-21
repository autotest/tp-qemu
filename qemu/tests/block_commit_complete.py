from qemu.tests import blk_commit


def run(test, params, env):
    """
    block_commit_complete test:
    1). Create live snapshot base->sn1->sn2->sn3->sn4
    2). Actions before start live commit
    3). Start live commit
    4). Actions during live commit
    5). Actions after finished
    6). Clean the environment no matter test pass or not

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    tag = params.get("source_image", "image1")
    commit_test = blk_commit.BlockCommit(test, params, env, tag)
    try:
        commit_test.create_snapshots()
        commit_test.action_before_start()
        commit_test.start()
        commit_test.do_steps("when_start")
        commit_test.action_after_finished()
    finally:
        commit_test.clean()
