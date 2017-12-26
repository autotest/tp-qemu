import logging

from virttest import utils_misc

from qemu.tests import blk_commit


class BlockCommitActive(blk_commit.BlockCommit):

    def __init__(self, test, params, env, tag):
        """
        Top image is the active one, the last one in the snapshot chain,
        and base image is the first snapshot, so the finally expected
        backing file is the source image
        """
        super(BlockCommitActive, self).__init__(test, params, env, tag)

        snapshot_chain = self.params["snapshot_chain"].split()
        self.top_image = snapshot_chain[-1]
        self.base_image = snapshot_chain[0]
        self.params["expected_image_file"] = "%s.%s" % (
            self.params["image_name"], self.params["image_format"])

    def reopen(self):
        """
        Reopen target image, then check if image file of the device is
        target images
        """
        params = self.parser_test_args()
        snapshot_format = params["snapshot_format"]
        top_image = utils_misc.get_path(self.data_dir, self.top_image)
        logging.info("reopen with block commit base image")
        self.vm.monitor.clear_event("BLOCK_JOB_COMPLETED")
        self.vm.block_reopen(self.device, top_image, snapshot_format)
        self.wait_for_finished()

    def verify_active_image(self):
        """
        Verify active image is the base image of commit job.
        """
        base_image = utils_misc.get_path(self.data_dir, self.base_image)
        if self.get_image_file() != base_image:
            self.test.fail("The active image after live commit is not the base image.")


def run(test, params, env):
    """
    Block commit with top is the active snapshot:
    1). Create live snapshot base->sn1->sn2->sn3->sn4
    2). Start live commit
    3). Wait for steady
    4). Reopen the image with block-job-complete
    5). Verify the active image and the backing file
    6). Reboot guest and verify guest alive
    7). Clean the environment no matter test pass or not

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    tag = params.get("source_image", "image1")
    commit_test = BlockCommitActive(test, params, env, tag)
    try:
        commit_test.create_snapshots()
        commit_test.start()
        commit_test.wait_for_steady()
        commit_test.reopen()
        commit_test.verify_active_image()
        commit_test.verify_backingfile()
        commit_test.reboot()
        commit_test.verify_alive()
    finally:
        commit_test.clean()
