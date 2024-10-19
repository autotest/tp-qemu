import random
import time

from virttest import utils_test

from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest
from provider.storage_benchmark import generate_instance


class BlockdevCommitFio(BlockDevCommitTest):
    def fio_thread(self):
        fio_options = self.params.get("fio_options")
        if fio_options:
            self.test.log.info("Start to run fio")
            self.fio = generate_instance(self.params, self.main_vm, "fio")
            fio_run_timeout = self.params.get_numeric("fio_timeout", 2400)
            self.fio.run(fio_options, fio_run_timeout)

    def commit_snapshots(self):
        for device in self.params["device_tag"].split():
            device_params = self.params.object_params(device)
            snapshot_tags = device_params["snapshot_tags"].split()
            self.device_node = self.get_node_name(device)
            device = self.get_node_name(snapshot_tags[-1])
            commit_cmd = backup_utils.block_commit_qmp_cmd
            cmd, args = commit_cmd(device)
            backup_utils.set_default_block_job_options(self.main_vm, args)
            job_id = args.get("job-id", device)
            self.main_vm.monitor.cmd(cmd, args)
            job_timeout = self.params.get_numeric("commit_job_timeout", 1800)
            job_utils.wait_until_block_job_completed(self.main_vm, job_id, job_timeout)

    def run_test(self):
        self.pre_test()
        try:
            bg_test = utils_test.BackgroundTest(self.fio_thread, "")
            bg_test.start()
            self.test.log.info("sleep random time before commit during fio")
            mint = self.params.get_numeric("sleep_min")
            maxt = self.params.get_numeric("sleep_max")
            time.sleep(random.randint(mint, maxt))
            self.commit_snapshots()
            self.verify_data_file()
        finally:
            # clean fio cause fio.run exit, then fio thread exit soon
            self.fio.clean(force=True)
            self.main_vm.verify_dmesg()
            self.post_test()


def run(test, params, env):
    """
    To verify the commit job can be completed after heavy IO finishes

    1. boot guest with system disk
    2. create snapshot
    3. run fio test in guest
    4. commit snapshot to base during fio running,
       wait commit done after fio done
    5. verify file's md5 after commit
    """

    block_test = BlockdevCommitFio(test, params, env)
    block_test.run_test()
