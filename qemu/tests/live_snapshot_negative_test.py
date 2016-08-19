import os
import logging

from virttest import utils_misc
from virttest import error_context
from virttest import data_dir
from qemu.tests.live_snapshot_basic import LiveSnapshot
from avocado.core import exceptions


class LiveSnapshotNegativeTest(LiveSnapshot):

    """
    Provide basic functions for live snapshot negative test cases.
    """

    def nonexist_snapshot_file(self):
        """
        Generate a non-existed path of snapshot file.
        """
        error_context.context("Generate a non-existed path of"
                              " snapshot file", logging.info)
        tmp_name = utils_misc.generate_random_string(5)
        dst = os.path.join(data_dir.get_tmp_dir(), tmp_name)
        path = os.path.join(dst, self.snapshot_file)
        if not os.path.exists(path):
            return path
        raise exceptions.TestFail("Path %s is existed." % path)

    def create_snapshot(self):
        """
        Create a live disk snapshot.
        """
        self.snapshot_file = self.nonexist_snapshot_file()
        kwargs = {"device": self.device,
                  "snapshot-file": self.snapshot_file,
                  "format": self.snapshot_format,
                  "mode": self.snapshot_mode}
        if 'format' not in kwargs:
            kwargs.update({"format": "qcow2"})
        if 'mode' not in kwargs:
            kwargs.update({"mode": "absolute-paths"})
        match_str = self.params.get("match_str")
        if self.snapshot_mode == "existing":
            match_str = match_str % self.snapshot_file

        error_context.context("Create live snapshot with non-existed path.",
                              logging.info)
        response = self.vm.monitor.cmd_qmp("blockdev-snapshot-sync", kwargs)
        if match_str not in str(response):
            raise exceptions.TestFail("Fail to get expected result."
                                      "%s is expected in %s" %
                                      (match_str, response))


@error_context.context_aware
def run(test, params, env):
    """
    live_snapshot_negative test:
    1). Create snapshot with non-existed path.
    2). Verify QMP error info as expected.

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    image_tag = params.get("image_name", "image1")
    image_params = params.object_params(image_tag)
    snapshot_test = LiveSnapshotNegativeTest(test, image_params, env, image_tag)
    snapshot_test.create_snapshot()
