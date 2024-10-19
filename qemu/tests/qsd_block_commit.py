from virttest import data_dir

from provider import backup_utils, job_utils
from provider.blockdev_commit_base import BlockDevCommitTest
from provider.qsd import QsdDaemonDev, add_vubp_into_boot
from provider.virt_storage.storage_admin import sp_admin


class QSDCommitTest(BlockDevCommitTest):
    def get_qsd_demon(self):
        qsd_name = self.params["qsd_namespaces"]
        qsd_ins = QsdDaemonDev(qsd_name, self.params)
        return qsd_ins

    def start_qsd(self):
        self.qsd = self.get_qsd_demon()
        self.qsd.start_daemon()

    def get_node_name(self, tag):
        if tag in self.params["device_tag"]:
            return "fmt_%s" % tag
        else:
            return "drive_%s" % tag

    def prepare_snapshot_file(self, snapshot_tags):
        self.snapshot_images = list(map(self.get_image_by_tag, snapshot_tags))
        params = self.params.copy()
        params.setdefault("target_path", data_dir.get_data_dir())
        for tag in snapshot_tags:
            image = sp_admin.volume_define_by_params(tag, params)
            image.hotplug(self.qsd)

    def create_snapshots(self, snapshot_tags, device):
        options = ["node", "overlay"]
        cmd = "blockdev-snapshot"
        for idx, tag in enumerate(snapshot_tags):
            params = self.params.object_params(tag)
            arguments = params.copy_from_keys(options)
            arguments["overlay"] = self.get_node_name(tag)
            if idx == 0:
                arguments["node"] = self.device_node
            else:
                arguments["node"] = self.get_node_name(snapshot_tags[idx - 1])
            self.qsd.monitor.cmd(cmd, dict(arguments))
            for info in self.disks_info:
                if device in info:
                    self.generate_tempfile(info[1], tag)

    def commit_snapshots(self):
        job_id_list = []
        for device in self.params["device_tag"].split():
            device_params = self.params.object_params(device)
            snapshot_tags = device_params["snapshot_tags"].split()
            self.device_node = self.get_node_name(device)
            options = ["base-node", "top-node", "speed"]
            arguments = self.params.copy_from_keys(options)
            arguments["base-node"] = self.get_node_name(device)
            arguments["top-node"] = self.get_node_name(snapshot_tags[-2])
            device = self.get_node_name(snapshot_tags[-1])
            if len(self.params["device_tag"].split()) == 1:
                backup_utils.block_commit(self.qsd, device, **arguments)
            else:
                commit_cmd = backup_utils.block_commit_qmp_cmd
                cmd, args = commit_cmd(device, **arguments)
                backup_utils.set_default_block_job_options(self.qsd, args)
                job_id = args.get("job-id", device)
                job_id_list.append(job_id)
                self.qsd.monitor.cmd(cmd, args)
        for job_id in job_id_list:
            job_utils.wait_until_block_job_completed(self.qsd, job_id)

    def pre_test(self):
        self.start_qsd()
        self.main_vm.params["extra_params"] = add_vubp_into_boot(
            self.params["device_tag"], self.params
        )
        super(QSDCommitTest, self).pre_test()

    def post_test(self):
        super(QSDCommitTest, self).post_test()
        self.qsd.stop_daemon()


def run(test, params, env):
    """
    Block commit base Test

    1. export image via qsd and boot guest with the exported image
    2. create 4 snapshots and save file in each snapshot
    3. commit snapshot 3 to snapshot 4
    4. verify files's md5
    """

    block_test = QSDCommitTest(test, params, env)
    block_test.run_test()
