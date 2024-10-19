from aexpect import ShellTimeoutError

from provider import backup_utils
from provider.blockdev_commit_base import BlockDevCommitTest


class BlockdevCommitWithIoerror(BlockDevCommitTest):
    def dd_io_error(self, root_dir, ori_filename, tar_filename, timeout=20):
        """dd file in snapshot"""
        self.session = self.main_vm.wait_for_login()
        self.file_info = self.files_info[0]
        ori_file_path = "%s/%s" % (root_dir, ori_filename)
        tar_file_path = "%s/%s" % (root_dir, tar_filename)
        dd_cmd = self.main_vm.params.get(
            "dd_cmd", "dd if=%s of=%s bs=1M count=500 oflag=direct"
        )
        mk_file_cmd = dd_cmd % (ori_file_path, tar_file_path)
        try:
            self.session.cmd(mk_file_cmd, timeout=timeout)
        except ShellTimeoutError:
            self.main_vm.verify_status("io-error")
            self.file_info.append(tar_filename)
        else:
            self.test.fail("Can dd large file on a small space")

    def create_snapshots(self, snapshot_tags, device):
        for info in self.disks_info:
            if device in info:
                self.generate_tempfile(info[1], filename="base", size="500M")
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
            self.main_vm.monitor.cmd(cmd, dict(arguments))
            for info in self.disks_info:
                if device in info:
                    self.dd_io_error(info[1], "base", tag)

    def md5_io_error_file(self):
        if not self.session:
            self.session = self.main_vm.wait_for_login()
        output = self.session.cmd_output("\n", timeout=120)
        if self.params["dd_done"] not in output:
            self.test.fail("dd not continue to run after vm resume")
        tar_file_path = "%s/%s" % (self.file_info[0], self.file_info[2])
        md5_cmd = "md5sum %s > %s.md5 && sync" % (tar_file_path, tar_file_path)
        self.session.cmd(md5_cmd, timeout=120)

    def commit_snapshots(self):
        for device in self.params["device_tag"].split():
            device_params = self.params.object_params(device)
            snapshot_tags = device_params["snapshot_tags"].split()
            self.device_node = self.get_node_name(device)
            device = self.get_node_name(snapshot_tags[-1])
            backup_utils.block_commit(self.main_vm, device)

    def verify_data_file(self):
        if not self.session:
            self.session = self.main_vm.wait_for_login()
        ori_file_md5 = ""
        for info in [self.file_info[1], self.file_info[2]]:
            file_path = "%s/%s" % (self.file_info[0], info)
            cat_cmd = "cat %s.md5" % file_path
            output = self.session.cmd_output(cat_cmd, timeout=120).split()[0]
            if not ori_file_md5:
                ori_file_md5 = output
        if ori_file_md5 != output:
            msg = "file ('%s' '%s') md5 mismatch" % (ori_file_md5, output)
            msg += "with value ('%s', '%s')" % (ori_file_md5, output)
            self.test.fail(msg)

    def op_after_commit(self):
        self.main_vm.resume()
        self.md5_io_error_file()
        self.verify_data_file()

    def run_test(self):
        self.pre_test()
        try:
            self.commit_snapshots()
            self.op_after_commit()
        finally:
            self.post_test()


def run(test, params, env):
    """
    Block commit after io error

    1). create small space(100M)
    2). start vm with 2G data disk and dd 500M file on it
    3). create snapshot node on small space
    4). dd 500M file in guest to casue vm paused with io-error
    5). do commit from snapshot to base
    6). continue vm, wait dd finished
    7). check files' md5 value in step1 and step6
    """

    block_test = BlockdevCommitWithIoerror(test, params, env)
    block_test.run_test()
