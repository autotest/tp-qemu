import logging
import random
import time

from autotest.client.shared import error, utils
from virttest import utils_misc
from virttest.utils_test.qemu import migration


@error.context_aware
def run(test, params, env):
    """
    KVM multi-host migration test:

    Migration execution progress is described in documentation
    for migrate method in class MultihostMigration.
    steps:
        1) try log to VM if login_before_pre_tests == yes
        2) before migration start pre_sub_test
        3) migration
        4) after migration start post_sub_test

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    preprocess_env = params.get("preprocess_env", "yes") == "yes"
    mig_protocol = params.get("mig_protocol", "tcp")
    mig_type = migration.MultihostMigration
    if mig_protocol == "fd":
        mig_type = migration.MultihostMigrationFd
    if mig_protocol == "exec":
        mig_type = migration.MultihostMigrationExec
    if "rdma" in mig_protocol:
        mig_type = migration.MultihostMigrationRdma

    class TestMultihostMigration(mig_type):
        def __init__(self, test, params, env):
            super(TestMultihostMigration, self).__init__(
                test, params, env, preprocess_env
            )
            self.srchost = self.params.get("hosts")[0]
            self.dsthost = self.params.get("hosts")[1]
            self.is_src = params["hostid"] == self.srchost
            self.vms = params["vms"].split()
            self.vm = params["vms"].split()[0]
            self.login_timeout = int(params.get("login_timeout", 360))
            self.random_timeout = 1

        @error.context_aware
        def before_migration(self, mig_data):
            def do_reboot(vm):
                reboot_method = mig_data.params.get("reboot_method", "system_reset")
                reboot_timeout = float(mig_data.params.get("reboot_timeout", 30))
                if self.is_src:
                    logging.info("Do '%s' before migraion...", reboot_method)

                    end_time = time.time() + reboot_timeout
                    while time.time() < end_time:
                        vm.monitor.clear_event("RESET")
                        vm.monitor.cmd(reboot_method)
                        reseted = utils_misc.wait_for(
                            lambda: vm.monitor.get_event("RESET"),
                            timeout=self.login_timeout,
                        )
                        if not reseted:
                            raise error.TestFail(
                                "Not found RESET event after " "execute 'system_reset'"
                            )
                        vm.monitor.clear_event("RESET")

                        time.sleep(self.random_timeout)

            error.context("Do reboot before migraion.", logging.info)
            vm = env.get_vm(params["main_vm"])
            bg = utils.InterruptedThread(do_reboot, (vm,))
            bg.start()
            time.sleep(self.random_timeout)

        @error.context_aware
        def migration_scenario(self, worker=None):
            if params.get("check_vm_before_migration", "yes") == "no":
                params["check_vm_needs_restart"] = "no"

            if params.get("enable_random_timeout") == "yes":
                min_t = int(params.get("min_random_timeout", 1))
                max_t = int(params.get("max_random_timeout", 5))
                self.random_timeout = random.randint(min_t, max_t)
                params["start_migration_timeout"] = self.random_timeout
                error.context(
                    "Start migration after %d seconds" % self.random_timeout,
                    logging.info,
                )

            self.migrate_wait([self.vm], self.srchost, self.dsthost)

    mig = TestMultihostMigration(test, params, env)
    mig.run()
