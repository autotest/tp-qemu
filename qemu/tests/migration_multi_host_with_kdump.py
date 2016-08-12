import logging
from autotest.client.shared import error
from autotest.client.shared.syncdata import SyncData
from virttest import utils_test
from qemu.tests.MigrationMultiHost import MigrationBase


@error.context_aware
def run(test, params, env):

    """
    KVM multi-host migration ping pong test:

    Migration execution progress is described in documentation
    for migrate method in class MultihostMigration.

    The test procedure:
    1) starts vm on master host.
    2) Configure kdump inside guest
    3) Implement kdump inside guest and pin the task to 1 cpu
    4) do ping pong migration until guest was verified to reboot succeed
    5) check "/var/crash" directory inside guest, whether dump file generates

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    mig_protocol = params.get("mig_protocol", "tcp")
    mig_type = utils_test.qemu.MultihostMigration
    if mig_protocol == "fd":
        mig_type = utils_test.qemu.MultihostMigrationFd
    if mig_protocol == "exec":
        mig_type = utils_test.qemu.MultihostMigrationExec
    if "rdma" in mig_protocol:
        mig_type = utils_test.qemu.MultihostMigrationRdma

    class TestMultihostMigration(mig_type, MigrationBase):

        """
        multihost migration test
        """

        def __init__(self, test, params, env):

            super(TestMultihostMigration, self).__init__(test, params, env)
            self.srchost = self.params.get("hosts")[0]
            self.dsthost = self.params.get("hosts")[1]
            super(TestMultihostMigration, self).__setup__(test, params, env,
                                                          self.srchost,
                                                          self.dsthost)
            self.crash_timeout = float(params.get("crash_timeout", 360))
            self.def_kernel_param_cmd = ("grubby --update-kernel=`grubby"
                                         " --default-kernel`"
                                         " --args=crashkernel=128M@16M")
            self.kernel_param_cmd = params.get("kernel_param_cmd",
                                               self.def_kernel_param_cmd)
            def_kdump_enable_cmd = ("chkconfig kdump on &&"
                                    " service kdump restart")
            self.kdump_enable_cmd = params.get("kdump_enable_cmd",
                                               def_kdump_enable_cmd)
            def_crash_kernel_prob_cmd = ("grep -q 1 /sys/kernel/"
                                         "kexec_crash_loaded")
            self.crash_kernel_prob_cmd = params.get("crash_kernel_prob_cmd",
                                                    def_crash_kernel_prob_cmd)
            self.crash_cmd = params.get("crash_cmd",
                                        "echo c > /proc/sysrq-trigger")
            self.vmcore_chk_cmd = params.get("vmcore_chk_cmd",
                                             "ls -R /var/crash | grep vmcore")
            self.vmcore_incomplete = "vmcore-incomplete"
            self.nvcpu = 1

        @error.context_aware
        def migration_scenario(self):

            error.context("Migration from %s to %s over protocol %s." %
                          (self.srchost, self.dsthost, mig_protocol),
                          logging.info)
            sync = SyncData(self.master_id(), self.hostid, self.hosts,
                            self.id, self.sync_server)

            def start_worker(mig_data):

                """
                force the Linux kernel to crash on src before migration

                :param mig_data: Data for migration
                """

                super(TestMultihostMigration, self).start_worker_guest_kdump(
                    mig_data, self.login_timeout, self.crash_kernel_prob_cmd,
                    self.kernel_param_cmd, self.kdump_enable_cmd, self.nvcpu,
                    self.crash_cmd)

            def check_worker(mig_data):

                """
                check weather generate vmcore file on dst after migration

                :param mig_data: Data for migration
                """

                super(TestMultihostMigration, self).check_worker_kdump(
                    mig_data, self.vmcore_chk_cmd, self.vmcore_incomplete)

            super(TestMultihostMigration, self).ping_pong_migrate(
                mig_type, sync, start_worker, check_worker)

    mig = TestMultihostMigration(test, params, env)
    mig.run()
