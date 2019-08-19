import logging

from avocado.utils import crypto
from avocado.utils import process

from virttest import error_context
from virttest import utils_misc

from qemu.tests.live_snapshot_basic import LiveSnapshot
from qemu.tests.qemu_guest_agent import QemuGuestAgentBasicCheckWin


class QemuGuestAgentSnapshotTest(QemuGuestAgentBasicCheckWin):

    @error_context.context_aware
    def setup(self, test, params, env):
        # pylint: disable=E1003
        if params["os_type"] == "windows":
            super(QemuGuestAgentSnapshotTest, self).setup(test, params, env)
        else:
            super(QemuGuestAgentBasicCheckWin, self).setup(test, params, env)

    @error_context.context_aware
    def _action_before_fsfreeze(self, *args):
        copy_timeout = int(self.params.get("copy_timeoout", 600))
        file_size = int(self.params.get("file_size", "1024"))
        tmp_name = utils_misc.generate_random_string(5)
        self.host_path = self.guest_path = "/tmp/%s" % tmp_name
        if self.params.get("os_type") != "linux":
            self.guest_path = r"c:\%s" % tmp_name

        error_context.context("Create a file in host.")
        process.run("dd if=/dev/urandom of=%s bs=1M count=%s"
                    % (self.host_path, file_size))
        self.orig_hash = crypto.hash_file(self.host_path)
        error_context.context("Transfer file from %s to %s" %
                              (self.host_path, self.guest_path), logging.info)
        self.bg = utils_misc.InterruptedThread(
            self.vm.copy_files_to,
            (self.host_path, self.guest_path),
            dict(verbose=True, timeout=copy_timeout))
        self.bg.start()

    @error_context.context_aware
    def _action_after_fsfreeze(self, *args):
        if self.bg.isAlive():
            image_tag = self.params.get("image_name", "image1")
            image_params = self.params.object_params(image_tag)
            snapshot_test = LiveSnapshot(self.test, self.params,
                                         self.env, image_tag)
            error_context.context("Creating snapshot", logging.info)
            snapshot_test.create_snapshot()
            error_context.context("Checking snapshot created successfully",
                                  logging.info)
            snapshot_test.check_snapshot()

    @error_context.context_aware
    def _action_before_fsthaw(self, *args):
        pass

    @error_context.context_aware
    def _action_after_fsthaw(self, *args):
        if self.bg:
            self.bg.join()
        # Make sure the returned file is identical to the original one
        try:
            self.host_path_returned = "%s-returned" % self.host_path
            self.vm.copy_files_from(self.guest_path, self.host_path_returned)
            error_context.context("comparing hashes", logging.info)
            self.curr_hash = crypto.hash_file(self.host_path_returned)
            if self.orig_hash != self.curr_hash:
                self.test.fail("Current file hash (%s) differs from "
                               "original one (%s)" % (self.curr_hash,
                                                      self.orig_hash))
        finally:
            error_context.context("Delete the created files.", logging.info)
            process.run("rm -rf %s %s" % (self.host_path,
                                          self.host_path_returned))
            session = self._get_session(self.params, None)
            self._open_session_list.append(session)
            cmd_del_file = "rm -rf %s" % self.guest_path
            if self.params.get("os_type") == "windows":
                cmd_del_file = r"del /f /q %s" % self.guest_path
            session.cmd(cmd_del_file)


def run(test, params, env):
    """
    Freeze guest + create live snapshot + thaw guest

    Test steps:
    1) Create a big file inside on host.
    2) Scp the file from host to guest.
    3) Freeze guest during file transfer.
    4) Create live snapshot.
    5) Thaw guest.
    6) Scp the file from guest to host.
    7) Compare hash of those 2 files.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """
    gagent_test = QemuGuestAgentSnapshotTest(test, params, env)
    gagent_test.execute(test, params, env)
