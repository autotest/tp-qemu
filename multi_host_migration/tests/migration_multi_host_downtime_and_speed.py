import logging

from autotest.client.shared import error, utils
from virttest import qemu_migration, utils_misc, utils_test, virt_vm
from virttest.utils_test.qemu import migration


@error.context_aware
def run(test, params, env):
    """
    KVM multi-host migration test:

    Migration execution progress is described in documentation
    for migrate method in class MultihostMigration.
    steps:
        1) login vm and load stress
        2) set downtime before migrate (optional)
        3) do migration
        4) set downtime/speed after migrate (optional)
        5) check downtime/speed value when migrate finished

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    mig_protocol = params.get("mig_protocol", "tcp")
    base_class = migration.MultihostMigration
    if mig_protocol == "fd":
        base_class = migration.MultihostMigrationFd
    if mig_protocol == "exec":
        base_class = migration.MultihostMigrationExec
    if "rdma" in mig_protocol:
        base_class = migration.MultihostMigrationRdma

    class TestMultihostMigration(base_class):
        def __init__(self, test, params, env):
            super(TestMultihostMigration, self).__init__(test, params, env)
            self.srchost = self.params.get("hosts")[0]
            self.dsthost = self.params.get("hosts")[1]
            self.is_src = params["hostid"] == self.srchost
            self.vms = params["vms"].split()

            self.sub_type = self.params.get("sub_type", None)
            self.mig_downtime = int(self.params.get("mig_downtime", "3"))
            self.max_downtime = int(self.params.get("max_mig_downtime", "10"))
            self.wait_mig_timeout = int(self.params.get("wait_mig_timeout", "30"))
            self.min_speed = self.params.get("min_migration_speed", "10")
            self.max_speed = self.params.get("max_migration_speed", "1000")
            self.ch_speed = int(self.params.get("change_speed_interval", 1))
            speed_count = float(self.params.get("count_of_change", 5))

            self.min_speed = utils.convert_data_size(self.min_speed, "M")
            self.max_speed = utils.convert_data_size(self.max_speed, "M")
            self.speed_step = int((self.max_speed - self.min_speed) / speed_count)

            if self.sub_type == "before_migrate":
                self.before_migration = self.before_migration_downtime
                self.post_migration = self.post_migration_before_downtime
            if self.sub_type == "after_migrate":
                self.post_migration = self.post_migration_downtime
            elif self.sub_type == "speed":
                self.post_migration = self.post_migration_speed
            elif self.sub_type == "stop_during":
                self.post_migration = self.post_migration_stop
            else:
                error.TestFail("Wrong subtest type selected %s" % (self.sub_type))

        def clean_up(self, vm):
            kill_bg_stress_cmd = params.get("kill_bg_stress_cmd", "killall -9 stress")

            logging.info("Kill the background stress test in the guest.")
            session = vm.wait_for_login(timeout=self.login_timeout)
            session.sendline(kill_bg_stress_cmd)
            session.close()

        @error.context_aware
        def check_mig_downtime(self, vm):
            logging.info("Check downtime after migration.")
            actual_downtime = int(vm.monitor.info("migrate").get("downtime"))
            if actual_downtime > self.mig_downtime * 1000:
                error = "Migration failed for setting downtime, "
                error += "Expected: '%d', Actual: '%d'" % (
                    self.mig_downtime,
                    actual_downtime,
                )
                raise error.TestFail(error)

        @error.context_aware
        def before_migration_downtime(self, mig_data):
            if self.is_src:
                vm = env.get_vm(params["main_vm"])
                error.context("Set downtime before migration.", logging.info)
                qemu_migration.set_downtime(vm, self.mig_downtime)

        @error.context_aware
        def post_migration_before_downtime(
            self,
            vm,
            cancel_delay,
            mig_offline,
            dsthost,
            vm_ports,
            not_wait_for_migration,
            fd,
            mig_data,
        ):
            try:
                vm.wait_for_migration(self.mig_timeout)
            except virt_vm.VMMigrateTimeoutError:
                raise error.TestFail(
                    "Migration failed with setting "
                    " downtime to %ds." % self.mig_downtime
                )

            logging.info(
                "Migration completed with downtime " "is %s seconds.", self.mig_downtime
            )

            self.check_mig_downtime(vm)
            vm.destroy(gracefully=False)

        @error.context_aware
        def post_migration_downtime(
            self,
            vm,
            cancel_delay,
            mig_offline,
            dsthost,
            vm_ports,
            not_wait_for_migration,
            fd,
            mig_data,
        ):
            logging.info("Set downtime after migration.")
            downtime = 0
            for downtime in range(1, self.max_downtime):
                try:
                    vm.wait_for_migration(self.wait_mig_timeout)
                    break
                except virt_vm.VMMigrateTimeoutError:
                    logging.info("Set downtime to %d seconds.", downtime)
                    qemu_migration.set_downtime(vm, downtime)

            try:
                vm.wait_for_migration(self.mig_timeout)
            except virt_vm.VMMigrateTimeoutError:
                raise error.TestFail(
                    "Migration failed with setting " " downtime to %ds." % downtime
                )

            self.mig_downtime = downtime - 1
            logging.info(
                "Migration completed with downtime " "is %s seconds.", self.mig_downtime
            )

            self.check_mig_downtime(vm)
            vm.destroy(gracefully=False)

        def post_migration_speed(
            self,
            vm,
            cancel_delay,
            mig_offline,
            dsthost,
            vm_ports,
            not_wait_for_migration,
            fd,
            mig_data,
        ):
            mig_speed = None

            for mig_speed in range(self.min_speed, self.max_speed, self.speed_step):
                try:
                    vm.wait_for_migration(self.wait_mig_timeout)
                    break
                except virt_vm.VMMigrateTimeoutError:
                    qemu_migration.set_speed(vm, "%sB" % (mig_speed))

            # Test migration status. If migration is not completed then
            # it kill program which creates guest load.
            try:
                vm.wait_for_migration(self.mig_timeout)
            except virt_vm.VMMigrateTimeoutError:
                raise error.TestFail(
                    "Migration failed with setting " " mig_speed to %sB." % mig_speed
                )

            logging.debug("Migration passed with mig_speed %sB", mig_speed)
            vm.destroy(gracefully=False)

        def post_migration_stop(
            self,
            vm,
            cancel_delay,
            mig_offline,
            dsthost,
            vm_ports,
            not_wait_for_migration,
            fd,
            mig_data,
        ):
            wait_before_mig = int(vm.params.get("wait_before_stop", "5"))

            try:
                vm.wait_for_migration(wait_before_mig)
            except virt_vm.VMMigrateTimeoutError:
                vm.pause()

            try:
                vm.wait_for_migration(self.mig_timeout)
            except virt_vm.VMMigrateTimeoutError:
                raise error.TestFail("Migration failed when vm is paused.")

        def migration_scenario(self, worker=None):
            @error.context_aware
            def start_worker(mig_data):
                error.context("Load stress in guest.", logging.info)
                vm = env.get_vm(params["main_vm"])
                session = vm.wait_for_login(timeout=self.login_timeout)
                bg_stress_test = params.get("bg_stress_test")
                check_running_cmd = params.get("check_running_cmd")

                bg = utils.InterruptedThread(
                    utils_test.run_virt_sub_test,
                    args=(
                        test,
                        params,
                        env,
                    ),
                    kwargs={"sub_type": bg_stress_test},
                )
                bg.start()

                def is_stress_running():
                    return session.cmd_status(check_running_cmd) == 0

                if not utils_misc.wait_for(is_stress_running, timeout=360):
                    raise error.TestFail(
                        "Failed to start %s in guest." % bg_stress_test
                    )

            def check_worker(mig_data):
                if not self.is_src:
                    vm = env.get_vm(params["main_vm"])
                    self.clean_up(vm)

            self.migrate_wait(
                self.vms, self.srchost, self.dsthost, start_worker, check_worker
            )

    mig = TestMultihostMigration(test, params, env)

    mig.run()
