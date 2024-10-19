import socket
import time

from virttest import env_process

from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest
from provider.nbd_image_export import QemuNBDExportImage


class BlockdevCommitServerDown(BlockDevCommitTest):
    def __init__(self, test, params, env):
        params["nbd_export_format"] = params["image_format"]
        self.nbd_export = QemuNBDExportImage(params, params["local_image_tag"])
        self.nbd_export.create_image()
        self.nbd_export.export_image()

        localhost = socket.gethostname()
        params["nbd_server"] = localhost if localhost else "localhost"
        params["images"] += " %s" % params["nbd_image_tag"]
        env_process.preprocess_vm(test, params, env, params["main_vm"])
        super(BlockdevCommitServerDown, self).__init__(test, params, env)

    def check_commit_running(self):
        tmo = self.params.get_numeric("commit_start_timeout", 5)

        # make sure commit is running, i.e. offset > 0
        for i in range(tmo):
            time.sleep(1)
            job = job_utils.get_block_job_by_id(self.main_vm, self.commit_job)
            if job["offset"] > 0:
                break
        else:
            self.test.fail("offset is 0 after %s seconds" % tmo)

    def check_commit_process(self):
        offset = None
        tmo = self.params.get_numeric("server_down_elapsed_time")

        # stop nbd server
        self.nbd_export.stop_export()

        # check commit job should hang
        for i in range(tmo):
            time.sleep(1)
            job = job_utils.get_block_job_by_id(self.main_vm, self.commit_job)
            if not job:
                self.test.fail("job cancelled in %d seconds" % tmo)
            if offset is None:
                offset = job["offset"]
            elif offset != job["offset"]:
                self.test.fail("offset changed: %s vs. %s" % (offset, job["offset"]))
        # resume nbd access
        self.nbd_export.export_image()

        # set max speed
        self.main_vm.monitor.set_block_job_speed(self.commit_job, 0)

        # commit job should complete
        job_utils.wait_until_block_job_completed(self.main_vm, self.commit_job)

    def commit_snapshots(self):
        device_params = self.params.object_params(self.params["nbd_image_tag"])
        snapshot_tags = device_params["snapshot_tags"].split()
        args = self.params.copy_from_keys(["speed"])
        device = self.get_node_name(snapshot_tags[-1])

        cmd, arguments = backup_utils.block_commit_qmp_cmd(device, **args)
        backup_utils.set_default_block_job_options(self.main_vm, arguments)
        self.main_vm.monitor.cmd(cmd, arguments)
        job = job_utils.query_block_jobs(self.main_vm)[0]
        self.commit_job = job["device"]
        self.check_commit_running()
        self.check_commit_process()

    def post_test(self):
        self.params["images"] += " %s" % self.params.get("local_image_tag")
        self.nbd_export.stop_export()
        super(BlockdevCommitServerDown, self).post_test()


def run(test, params, env):
    """
    Block commit remote storage server down test

    1. create a data disk and export it by qemu-nbd
    2. boot vm with the exported nbd disk as its data disk
    3. do live snapshots for the data disk
    4. create a file on data disk and do live commit
    5. stop nbd server
    6. check the commit process should hang, offset keeps the same
    7. start nbd server to export disk again
    8. live commit should complete
    """

    block_test = BlockdevCommitServerDown(test, params, env)
    block_test.run_test()
