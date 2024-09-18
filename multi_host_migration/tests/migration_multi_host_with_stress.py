import logging

from autotest.client.shared import error, utils
from virttest import utils_misc, utils_test
from virttest.utils_test.qemu import migration


@error.context_aware
def run(test, params, env):
    """
    KVM multi-host migration test:

    Migration execution progress is described in documentation
    for migrate method in class MultihostMigration.
    steps:
        1) boot vm and login, load stress in guest
        2) do migration
        3) wait for a while and stop stress
        4) login guest when migrate done

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    preprocess_env = params.get("preprocess_env", "yes") == "yes"
    mig_protocol = params.get("mig_protocol", "tcp")
    mig_type = migration.MultihostMigration
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
            self.need_cleanup = params.get("need_cleanup", "yes") == "yes"
            self.driver_load_cmd = params.get("driver_load_cmd")
            if self.driver_load_cmd:
                self.nic_index = 1
                self.login_timeout = 120
            else:
                self.nic_index = 0
                self.login_timeout = int(params.get("login_timeout", 240))
            self.bg = None

        def migration_scenario(self):
            def clean_up(vm):
                kill_bg_stress_cmd = params.get(
                    "kill_bg_stress_cmd", "killall -9 stress"
                )

                logging.info("Kill the background test in guest.")
                session = vm.wait_for_login(
                    timeout=self.login_timeout, nic_index=self.nic_index
                )
                if self.params.get("bg_stress_test") == "driver_load":
                    if self.bg and self.bg.is_alive():
                        self.bg.join()
                    output = session.cmd_output("ipconfig || ifconfig")
                    logging.info("Guest network status:\n %s", output)
                    session.cmd(self.driver_load_cmd)
                else:
                    s, o = session.cmd_status_output(kill_bg_stress_cmd)
                    if s:
                        raise error.TestFail(
                            "Failed to kill the background" " test in guest: %s" % o
                        )
                session.close()

            @error.context_aware
            def start_worker(mig_data):
                logging.info("Try to login guest before migration test.")
                vm = env.get_vm(params["main_vm"])
                bg_stress_test = self.params.get("bg_stress_test")
                session = vm.wait_for_login(
                    timeout=self.login_timeout, nic_index=self.nic_index
                )

                error.context("Do stress test before migration.", logging.info)
                check_running_cmd = params.get("check_running_cmd")

                self.bg = utils.InterruptedThread(
                    utils_test.run_virt_sub_test,
                    args=(
                        test,
                        params,
                        env,
                    ),
                    kwargs={"sub_type": bg_stress_test},
                )

                self.bg.start()

                def check_running():
                    return session.cmd_status(check_running_cmd) == 0

                if check_running_cmd:
                    if not utils_misc.wait_for(check_running, timeout=360):
                        raise error.TestFail(
                            "Failed to start %s in guest." % bg_stress_test
                        )

            def check_worker(mig_data):
                if not self.is_src and self.need_cleanup:
                    vm = env.get_vm(params["main_vm"])
                    clean_up(vm)

            if params.get("check_vm_before_migration", "yes") == "no":
                params["check_vm_needs_restart"] = "no"

            self.migrate_wait(
                self.vms, self.srchost, self.dsthost, start_worker, check_worker
            )

    mig = TestMultihostMigration(test, params, env)
    mig.run()
