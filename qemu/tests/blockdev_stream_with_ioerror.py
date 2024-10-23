from aexpect import ShellTimeoutError
from virttest import error_context

from provider.blockdev_stream_base import BlockDevStreamTest


class BlockdevStreamWithIoerror(BlockDevStreamTest):
    """Do block stream after io-error"""

    def dd_io_error(self, root_dir, ori_filename, tar_filename, timeout=20):
        """Generate temp data file in guest"""
        self.session = self.main_vm.wait_for_login()
        self.file_info = self.files_info[0]
        ori_file_path = "%s/%s" % (root_dir, ori_filename)
        tar_file_path = "%s/%s" % (root_dir, tar_filename)
        dd_cmd = self.main_vm.params.get(
            "dd_cmd", "dd if=%s of=%s bs=1M count=60 oflag=direct"
        )
        mk_file_cmd = dd_cmd % (ori_file_path, tar_file_path)
        try:
            self.session.cmd(mk_file_cmd, timeout=timeout)
        except ShellTimeoutError:
            self.main_vm.verify_status("io-error")
            self.file_info.append(tar_filename)
        else:
            self.test.fail("Can dd large file on a small space")

    def snapshot_test(self):
        for info in self.disks_info.values():
            self.generate_tempfile(info[1], filename="base", size="60M")
            self.dd_io_error(info[1], "base", "base_io_error")
        self.create_snapshot()

    def md5_io_error_file(self):
        if not self.session:
            self.session = self.main_vm.wait_for_login()
        output = self.session.cmd_output("\n", timeout=120)
        if self.params["dd_done"] not in output:
            self.test.fail("dd not continue to run after vm resume")
        tar_file_path = "%s/%s" % (self.file_info[0], self.file_info[2])
        md5_cmd = "md5sum %s > %s.md5 && sync" % (tar_file_path, tar_file_path)
        self.session.cmd(md5_cmd, timeout=120)

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

    def op_after_stream(self):
        self.main_vm.resume()
        self.md5_io_error_file()
        self.verify_data_file()

    def do_test(self):
        self.snapshot_test()
        self.blockdev_stream()
        self.op_after_stream()


@error_context.context_aware
def run(test, params, env):
    """
    Test VM block device stream feature
    1) Create small space
    2) Start VM with 500M  data disk created on small space
    3) dd a 60M file base on data disk and record its md5
    4) dd 60M base_io_eror in guest to cause vm paused with io-error
    5) Create snapshot for the data disk
    6) Do stream from data disk to snapshot file
    7) Continue vm, wait dd finished, md5sum io_error_file
    8) Verify md5 between base and base_io_error

    :param test: QEMU test object.
    :param params: Dictionary with the test parameters.
    :param env: Dictionary with test environment.

    """
    stream_test = BlockdevStreamWithIoerror(test, params, env)
    stream_test.run_test()
