import time

from provider.blockdev_mirror_nowait import BlockdevMirrorNowaitTest


class BlockdevMirrorSyncModeNoneTest(BlockdevMirrorNowaitTest):
    """Block mirror with sync mode:none"""

    def _verify_file_not_exist(self, dir_list, none_existed_files):
        session = self.clone_vm.wait_for_login()
        try:
            for idx, f in enumerate(none_existed_files):
                file_path = "%s/%s" % (dir_list[idx], f)
                cat_cmd = "ls %s" % file_path

                s, o = session.cmd_status_output(cat_cmd)
                if s == 0:
                    self.test.fail("File (%s) exists" % f)
                elif "No such file" not in o.strip():
                    self.test.fail("Unknown error: %s" % o)
        finally:
            session.close()

    def verify_data_files(self):
        dir_list = [self.disks_info[t][1] for t in self._source_images]
        none_existed_files = [self.files_info[t].pop(0) for t in self._source_images]

        # the second file should exist
        super(BlockdevMirrorSyncModeNoneTest, self).verify_data_files()

        # the first file should not exist
        self._verify_file_not_exist(dir_list, none_existed_files)

    def generate_inc_files(self):
        return list(map(self.generate_data_file, self._source_images))

    def wait_mirror_jobs_completed(self):
        # Sleep some time here to wait for block-mirror done, please be noted
        # that block-mirror with sync mode "none" is quite different from
        # others, the job status turns into 'READY' very quickly after a new
        # file is created, and sometimes, the current-progress and
        # total-progress are same, but in fact, the mirror is still running.
        # This is expected.
        time.sleep(int(self.params.get("sync_none_mirror_timeout", "20")))
        super(BlockdevMirrorSyncModeNoneTest, self).wait_mirror_jobs_completed()

    def reboot_vm(self):
        """
        Reboot VM to make sure the data is flushed to disk, then data
        generated after block-mirror is copied.
        Note: 'dd oflag=direct/sync' cannot guarantee data is flushed.
        """
        self.main_vm.reboot(method="system_reset")

    def do_test(self):
        self.reboot_vm()
        self.blockdev_mirror()
        self.generate_inc_files()
        self.wait_mirror_jobs_completed()
        self.check_mirrored_block_nodes_attached()
        self.clone_vm_with_mirrored_images()
        self.verify_data_files()


def run(test, params, env):
    """
    Block mirror with sync mode:none

    test steps:
        1. boot VM with a 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a target disk for mirror to VM via qmp commands
        5. do block-mirror with sync mode none
        6. create another file
        7. check the mirror disk is attached
        8. restart VM with the mirror disk
        9. the first file doesn't exist while the second one exists

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    mirror_test = BlockdevMirrorSyncModeNoneTest(test, params, env)
    mirror_test.run_test()
