from virttest import utils_misc, utils_test

from qemu.tests import blk_commit


class BlockCommitStress(blk_commit.BlockCommit):
    def load_stress(self):
        """
        load IO/CPU/Memoery stress in guest
        """
        self.test.log.info("launch stress app in guest")
        args = (self.test, self.params, self.env, self.params["stress_test"])
        bg_test = utils_test.BackgroundTest(utils_test.run_virt_sub_test, args)
        bg_test.start()
        if not utils_misc.wait_for(bg_test.is_alive, first=10, step=3, timeout=100):
            self.test.fail("background test start failed")
        if not utils_misc.wait_for(self.app_running, timeout=360, step=5):
            self.test.fail("stress app isn't running")

    def unload_stress(self):
        """
        stop stress app
        """

        def _unload_stress():
            session = self.get_session()
            cmd = self.params.get("stop_cmd")
            session.sendline(cmd)
            session.close()
            return self.app_running()

        self.test.log.info("stop stress app in guest")
        stopped = utils_misc.wait_for(
            _unload_stress,
            first=2.0,
            text="wait stress app quit",
            step=1.0,
            timeout=self.params["wait_timeout"],
        )
        if not stopped:
            self.test.log.warning("stress app is still running")

    def app_running(self):
        """
        check stress app really run in background
        """
        session = self.get_session()
        cmd = self.params.get("check_cmd")
        status = session.cmd_status(cmd, timeout=120)
        session.close()
        return status == 0

    def verify_backingfile(self):
        """
        check no backingfile found after commit job done via qemu-img info;
        """
        self.test.log.info("Check image backing-file")
        exp_img_file = self.params["expected_image_file"]
        exp_img_file = utils_misc.get_path(self.data_dir, exp_img_file)
        self.test.log.debug(
            "Expected image file read from config file is '%s'", exp_img_file
        )

        backingfile = self.get_backingfile("monitor")
        if backingfile:
            self.test.log.info(
                "Got backing-file: #%s# by 'info/query block' in #%s# " "monitor",
                backingfile,
                self.vm.monitor.protocol,
            )
        if exp_img_file == backingfile:
            self.test.log.info("check backing file with monitor passed")
        else:
            self.test.fail(
                "backing file is different with the expected one. "
                "expecting: %s, actual: %s" % (exp_img_file, backingfile)
            )


def run(test, params, env):
    """
    block_commit_stress test:
    1). load stress in guest
    2). create live snapshot base->sn1->sn2->sn3->sn4
    3). merge sn3 to sn1(sn3->sn1), the snapshot chain should be base->sn1->sn4
    4). commit block device and wait to finished
    5). check backing file after commit
    6). quit stress app
    7). reboot and verify guest can response correctly

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    tag = params.get("source_image", "image1")
    stress_test = BlockCommitStress(test, params, env, tag)
    try:
        stress_test.action_before_start()
        stress_test.create_snapshots()
        stress_test.start()
        stress_test.action_after_finished()
    finally:
        stress_test.clean()
