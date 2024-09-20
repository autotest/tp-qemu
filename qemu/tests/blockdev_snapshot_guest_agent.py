import logging
import time

from virttest import error_context, guest_agent, utils_test

from provider.blockdev_snapshot_base import BlockDevSnapshotTest

LOG_JOB = logging.getLogger("avocado.test")


class BlockdevSnapshotGuestAgentTest(BlockDevSnapshotTest):
    def pre_test(self):
        super(BlockdevSnapshotGuestAgentTest, self).pre_test()
        params = self.params.object_params(self.params["agent_name"])
        params["monitor_filename"] = self.main_vm.get_serial_console_filename(
            self.params["agent_name"]
        )
        self.guest_agent = guest_agent.QemuAgent(
            self.main_vm,
            self.params["agent_name"],
            self.params["agent_serial_type"],
            params,
        )
        session = self.main_vm.wait_for_login()
        try:
            if session.cmd_status(self.params["enable_nonsecurity_files_cmd"]) != 0:
                session.cmd_status(self.params["enable_permissive_cmd"])
        finally:
            session.close()

    def scp_test(self):
        utils_test.run_file_transfer(self.test, self.params, self.env)

    @error_context.context_aware
    def create_snapshot(self):
        bg_test = utils_test.BackgroundTest(self.scp_test, "")
        bg_test.start()
        LOG_JOB.info("Sleep some time to wait for scp's preparation done")
        time.sleep(30)
        error_context.context("freeze guest before snapshot", LOG_JOB.info)
        self.guest_agent.fsfreeze()
        super(BlockdevSnapshotGuestAgentTest, self).create_snapshot()
        error_context.context("thaw guest after snapshot", LOG_JOB.info)
        self.guest_agent.fsthaw()
        bg_test.join()


def run(test, params, env):
    """
    Do snapshot with guest agent

    1) start VM with system disk
    2) create target disk with qmp command
    3) scp large file from host to guest
    4) freeze guest fs, check fs status
    5) do snapshot
    6) thraw guest fs, check fs status
    7) wait until scp done, shutdown vm, then restart it with snapshot
    :param test: test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    base_image = params.get("images", "image1").split()[0]
    params.setdefault("image_name_%s" % base_image, params["image_name"])
    params.setdefault("image_format_%s" % base_image, params["image_format"])
    snapshot_guest_agent = BlockdevSnapshotGuestAgentTest(test, params, env)
    snapshot_guest_agent.run_test()
