from provider.blockdev_live_backup_base import BlockdevLiveBackupBaseTest
from provider.job_utils import check_block_jobs_started, wait_until_block_job_completed


class BlockdevIncbkFilterNodeTest(BlockdevLiveBackupBaseTest):
    """live backup with filter-node-name test"""

    def __init__(self, test, params, env):
        super(BlockdevIncbkFilterNodeTest, self).__init__(test, params, env)
        self._jobid = "backup_%s_job" % self._source_nodes[0]
        self._full_backup_options.update(
            {
                "device": self._source_nodes[0],
                "target": self._full_bk_nodes[0],
                "filter-node-name": self.params["filter_node_name"],
                "job-id": self._jobid,
            }
        )

    def check_node_attached(self, node):
        """The filter node name should be set when doing backup"""
        for item in self.main_vm.monitor.query("block"):
            if (
                self._source_images[0] in item["qdev"]
                and item["inserted"].get("node-name") == node
            ):
                break
        else:
            self.test.fail("Filter node (%s) is not attached" % node)

    def do_full_backup(self):
        self.main_vm.monitor.cmd("blockdev-backup", self._full_backup_options)

    def set_max_job_speed(self):
        self.main_vm.monitor.cmd(
            "block-job-set-speed", {"device": self._jobid, "speed": 0}
        )

    def do_test(self):
        self.do_full_backup()
        check_block_jobs_started(
            self.main_vm,
            [self._jobid],
            self.params.get_numeric("job_started_timeout", 30),
        )
        self.check_node_attached(self.params["filter_node_name"])
        self.set_max_job_speed()
        wait_until_block_job_completed(self.main_vm, self._jobid)
        self.check_node_attached(self._source_nodes[0])
        self.prepare_clone_vm()
        self.verify_data_files()


def run(test, params, env):
    """
    live backup with filter-node-name test

    test steps:
        1. boot VM with a 2G data disk
        2. format the data disk and mount it
        3. create a file
        4. add a target disk for backup to VM via qmp commands
        5. do blockdev-backup with filter node set
        6. check filter node name is set when doing backup
        7. wait till complete the backup job
        8. check the backup disk is attached
        9. restart vm with the backup disk as its data disk
       10. check the file's md5sum

    :param test: test object
    :param params: test configuration dict
    :param env: env object
    """
    bk_test = BlockdevIncbkFilterNodeTest(test, params, env)
    bk_test.run_test()
