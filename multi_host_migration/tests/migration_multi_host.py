import logging
import random
import time

from autotest.client.shared import error
from virttest import utils_test
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
            self.pre_sub_test = params.get("pre_sub_test")
            self.post_sub_test = params.get("post_sub_test")
            self.login_before_pre_tests = params.get("login_before_pre_tests", "no")
            self.mig_bg_command = params.get(
                "migration_bg_command", "cd /tmp; nohup ping localhost &"
            )
            self.mig_bg_check_command = params.get(
                "migration_bg_check_command", "pgrep ping"
            )
            self.mig_bg_kill_command = params.get(
                "migration_bg_kill_command", "pkill -9 ping"
            )
            self.need_to_login = params.get("need_to_login", "no")

        def run_pre_sub_test(self):
            # is source host
            if self.is_src:
                if self.pre_sub_test:
                    if self.login_before_pre_tests == "yes":
                        vm = env.get_vm(params["main_vm"])
                        vm.wait_for_login(timeout=self.login_timeout)
                    error.context(
                        "Run sub test '%s' before migration on src" % self.pre_sub_test,
                        logging.info,
                    )
                    utils_test.run_virt_sub_test(test, params, env, self.pre_sub_test)

        def run_post_sub_test(self):
            # is destination host
            if not self.is_src:
                if self.post_sub_test:
                    error.context(
                        "Run sub test '%s' after migration on dst" % self.post_sub_test,
                        logging.info,
                    )
                    utils_test.run_virt_sub_test(test, params, env, self.post_sub_test)

        def migration_scenario(self, worker=None):
            def start_worker(mig_data):
                logging.info("Try to login guest before migration test.")
                vm = env.get_vm(params["main_vm"])

                session = vm.wait_for_login(timeout=self.login_timeout)
                logging.debug("Sending command: '%s'", self.mig_bg_command)
                s, o = session.cmd_status_output(self.mig_bg_command)
                if s != 0:
                    raise error.TestError(
                        "Failed to run bg cmd in guest," " Output is '%s'." % o
                    )
                time.sleep(5)

            def check_worker(mig_data):
                if not self.is_src:
                    logging.info("Try to login guest after migration test.")
                    vm = env.get_vm(params["main_vm"])
                    serial_login = params.get("serial_login")
                    if serial_login == "yes":
                        session = vm.wait_for_serial_login(timeout=self.login_timeout)
                    else:
                        session = vm.wait_for_login(timeout=self.login_timeout)

                    logging.info("Check the background command in the guest.")
                    s, o = session.cmd_status_output(self.mig_bg_check_command)
                    if s:
                        raise error.TestFail(
                            "Background command not found," " Output is '%s'." % o
                        )

                    logging.info("Kill the background command in the guest.")
                    session.sendline(self.mig_bg_kill_command)
                    session.close()

            if params.get("check_vm_before_migration", "yes") == "no":
                params["check_vm_needs_restart"] = "no"

            if params.get("enable_random_timeout") == "yes":
                min_t = int(params.get("min_random_timeout", 1))
                max_t = int(params.get("max_random_timeout", 5))
                random_timeout = random.randint(min_t, max_t)
                params["start_migration_timeout"] = random_timeout
                error.context(
                    "Wait for %d seconds, then do migration." % random_timeout,
                    logging.info,
                )

            self.run_pre_sub_test()

            if self.need_to_login == "yes":
                self.migrate_wait(
                    [self.vm],
                    self.srchost,
                    self.dsthost,
                    start_work=start_worker,
                    check_work=check_worker,
                )
            else:
                self.migrate_wait([self.vm], self.srchost, self.dsthost)

            self.run_post_sub_test()

    mig = TestMultihostMigration(test, params, env)
    mig.run()
