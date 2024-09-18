import logging

from autotest.client.shared import error
from virttest import utils_test, virt_vm
from virttest.utils_test.qemu import migration


@error.context_aware
def run(test, params, env):
    """
    KVM multi-host migration test:

    Migration execution progress is described in documentation
    for migrate method in class MultihostMigration.

    The test procedure:
    1) starts vm on master host.
    2) query migrate capabilities, query cache size, enable/disable xbzrle
    3) a. Migrate guest with heavy loaded inside guest (running a dirty page
       generator) and compare the total time, downtime and transferred
       ram with and without xbzrle
       b. Migrate guest without heavy loaded inside guest and compare the
       migration total time, downtime and transferred ram with and without
       xbzrle
    4) With xbzrle enabled, the total time, downtime and transferred ram
       should less than disabled
    5) Check live migration statistics for xbzrle specific options

    :param test: kvm test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """

    mig_protocol = params.get("mig_protocol", "tcp")
    mig_type = migration.MultihostMigration
    if mig_protocol == "fd":
        mig_type = migration.MultihostMigrationFd
    if mig_protocol == "exec":
        mig_type = migration.MultihostMigrationExec
    if "rdma" in mig_protocol:
        mig_type = migration.MultihostMigrationRdma

    class TestMultihostMigration(mig_type, migration.MigrationBase):
        """
        multihost migration test
        """

        def __init__(self, test, params, env):
            super(TestMultihostMigration, self).__init__(test, params, env)
            self.srchost = self.params.get("hosts")[0]
            self.dsthost = self.params.get("hosts")[1]
            super(TestMultihostMigration, self).__setup__(
                test, params, env, self.srchost, self.dsthost
            )
            self.need_set_cache_size = set_cache_size == "yes"
            self.need_stress = need_stress == "yes"
            self.need_cleanup = self.need_stress
            self.sub_type = params.get("sub_type")
            self.sub_test = params.objects("sub_test")
            for i in range(1, len(self.sub_test)):
                if self.sub_test[i].strip() == "enable":
                    self.sub_test[i] = True
                else:
                    self.sub_test[i] = False
            if self.sub_type == "before_migrate_capability":
                self.before_migration = self.before_migration_capability
                self.post_migration = self.post_migration_capability
            if self.sub_type == "before_migrate_cache_size":
                self.before_migration = self.before_migration_cache_size_speed
                self.post_migration = self.post_migration_capability_with_xbzrle_off_on
            if self.sub_type == "after_migrate_cache_size":
                self.before_migration = self.before_migration_capability_with_xbzrle_on
                self.post_migration = self.post_migration_set_cache_size

        def set_xbzrle(self):
            """
            enable/disable xbzrle
            """

            for i in range(1, len(self.sub_test)):
                self.set_migration_capability(self.sub_test[i], "xbzrle")
                self.capabilitys.append("xbzrle")
                self.capabilitys_state.append(self.sub_test[i])
                self.get_migration_capability(len(self.capabilitys) - 1)
                self.capabilitys.pop()
                self.capabilitys_state.pop()

        @error.context_aware
        def get_mig_totaltime_downtime_transferred_ram(self, vm):
            """
            get total time, downtime and transferred ram after migration

            :param vm: vm object
            """

            error.context(
                "Get total time, downtime and transferred ram " "after migration.",
                logging.info,
            )
            downtime = int(vm.monitor.info("migrate").get("downtime"))
            total_time = int(vm.monitor.info("migrate").get("total-time"))
            transferred_ram = int(
                vm.monitor.info("migrate").get("ram").get("transferred")
            )
            mig_downtime_list.append(downtime)
            mig_total_time_list.append(total_time)
            transferred_ram_list.append(transferred_ram)
            logging.info(
                "The total time is %d, downtime is %d and "
                "transferred ram is %d after migration",
                total_time,
                downtime,
                transferred_ram,
            )

        @error.context_aware
        def check_mig_totaltime_downtime_transferred_ram(self):
            """
            check total time, downtime and transferred ram after migration
            the items in list should be decrease
            """

            if self.is_src:
                error.context(
                    "Check total time, downtime and transferred ram"
                    " after migration.",
                    logging.info,
                )
                logging.info("Total time list: %s", str(mig_total_time_list))
                logging.info("Downtime list: %s", str(mig_downtime_list))
                logging.info("Transferred ram list: %s", str(transferred_ram_list))
                for i in range(len(mig_total_time_list)):
                    if min(mig_total_time_list) != mig_total_time_list[-1]:
                        raise error.TestFail(
                            "The total time of migration is "
                            "error, %s should be minimum, "
                            "but actual is %s"
                            % (mig_total_time_list[-1], min(mig_total_time_list))
                        )
                    else:
                        mig_total_time_list.pop()
                    if min(mig_downtime_list) != mig_downtime_list[-1]:
                        raise error.TestFail(
                            "The downtime of migration is "
                            "error, %s should be minimum, "
                            "but actual is %s"
                            % (mig_downtime_list[-1], min(mig_downtime_list))
                        )
                    else:
                        mig_downtime_list.pop()
                    if min(transferred_ram_list) != transferred_ram_list[-1]:
                        raise error.TestFail(
                            "The transferred ram of migration is error, "
                            "%s should be minimum, but actual is %s"
                            % (transferred_ram_list[-1], min(transferred_ram_list))
                        )
                    else:
                        transferred_ram_list.pop()

        def before_migration_capability(self, mig_data):
            """
            get migration capability (xbzrle/cache_size)
            enable/disable xbzrle

            :param mig_data: Data for migration
            """

            if self.is_src:
                self.get_migration_capability()
                self.get_migration_cache_size()
                if self.sub_test[0] == "set_xbzrle":
                    self.set_xbzrle()

        def before_migration_cache_size_speed(self, mig_data):
            """
            enable xbzrle, set cache size and set speed to max
            before migration

            :param mig_data: Data for migration
            """

            if self.is_src:
                if self.need_set_cache_size:
                    self.set_xbzrle()
                    self.set_migration_cache_size(int(self.cache_size[1]))
                    self.get_migration_cache_size(1)
                if self.need_set_speed:
                    self.set_migration_speed(self.max_speed)

        def before_migration_capability_with_xbzrle_on(self, mig_data):
            """
            enable xbzrle and set speed to max before migration

            :param mig_data: Data for migration
            """

            if self.is_src:
                self.set_xbzrle()
                if self.need_set_speed:
                    self.set_migration_speed(self.max_speed)

        @error.context_aware
        def post_migration_capability(
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
            """
            get total time, downtime and transferred ram after migration

            :param vm: vm object
            :param cancel_delay: If provided, specifies a time duration
                   after which migration will be canceled.  Used for
                   testing migrate_cancel.
            :param mig_offline: If True, pause the source VM before migration
            :param dsthost: Destination host
            :param vm_ports: vm migration ports
            :param not_wait_for_migration: If True migration start but not
                   wait till the end of migration.
            :param fd: File descriptor for migration
            :param mig_data: Data for migration
            """

            try:
                vm.wait_for_migration(self.migration_timeout)
            except virt_vm.VMMigrateTimeoutError:
                raise error.TestFail(
                    "Migration failed with setting " "xbzrle to false."
                )
            logging.info("Migration completed with xbzrle false")
            self.get_mig_totaltime_downtime_transferred_ram(vm)
            vm.destroy(gracefully=False)

        @error.context_aware
        def post_migration_capability_with_xbzrle_off_on(
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
            """
            get total time, downtime and transferred ram after migration

            :param vm: vm object
            :param cancel_delay: If provided, specifies a time duration
                   after which migration will be canceled.  Used for
                   testing migrate_cancel.
            :param mig_offline: If True, pause the source VM before migration
            :param dsthost: Destination host
            :param vm_ports: vm migration ports
            :param not_wait_for_migration: If True migration start but not
                   wait till the end of migration.
            :param fd: File descriptor for migration
            :param mig_data: Data for migration
            """

            if self.need_set_cache_size:
                cache_size = self.cache_size[1]
            else:
                cache_size = self.cache_size[0]
            try:
                vm.wait_for_migration(self.mig_timeout)
            except virt_vm.VMMigrateTimeoutError:
                raise error.TestFail(
                    "Migration failed with setting cache " "size to %s." % cache_size
                )
            logging.info("Migration completed with cache size %s" "", cache_size)
            self.get_mig_totaltime_downtime_transferred_ram(vm)
            vm.destroy(gracefully=False)

        @error.context_aware
        def post_migration_set_cache_size(
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
            """
            set cache size during migration
            get cache size after migration
            get total time, downtime and transferred ram after migration
            git migration info

            :param vm: vm object
            :param cancel_delay: If provided, specifies a time duration
                   after which migration will be canceled.  Used for
                   testing migrate_cancel.
            :param mig_offline: If True, pause the source VM before migration
            :param dsthost: Destination host
            :param vm_ports: vm migration ports
            :param not_wait_for_migration: If True migration start but not
                   wait till the end of migration.
            :param fd: File descriptor for migration
            :param mig_data: Data for migration
            """

            try:
                vm.wait_for_migration(5)
            except virt_vm.VMMigrateTimeoutError:
                logging.info(
                    "Set cache size to %s during migration" ".", self.cache_size[1]
                )
                self.set_migration_cache_size(int(self.cache_size[1]))
            try:
                vm.wait_for_migration(self.mig_timeout)
            except virt_vm.VMMigrateTimeoutError:
                raise error.TestFail(
                    "Migration failed with setting cache "
                    "size to %s." % self.cache_size[1]
                )
            logging.info(
                "Migration completed with cache size %s" "", self.cache_size[1]
            )
            self.get_migration_cache_size(1)
            self.get_mig_totaltime_downtime_transferred_ram(vm)
            self.get_migration_info(vm)
            vm.destroy(gracefully=False)

        @error.context_aware
        def migration_scenario(self):
            error.context(
                "Migration from %s to %s over protocol %s."
                % (self.srchost, self.dsthost, mig_protocol),
                logging.info,
            )

            def start_worker(mig_data):
                """
                enable/disable stress in guest on src host
                """

                if self.need_stress:
                    self.start_stress()
                else:
                    logging.info("No need to start stress test")

            def check_worker(mig_data):
                """
                kill background test in guest on dst host
                """

                if not self.is_src:
                    for vm in mig_data.vms:
                        if vm.is_paused():
                            vm.resume()
                        if not utils_test.qemu.guest_active(vm):
                            raise error.TestFail("Guest not active " "after migration")
                    if self.need_cleanup:
                        self.clean_up(self.kill_bg_stress_cmd, vm)
                    else:
                        logging.info("No need to kill the background " "test in guest.")
                    vm.reboot()
                    vm.destroy()

            self.migrate_wait(
                [self.vm], self.srchost, self.dsthost, start_worker, check_worker
            )

    set_cache_size_list = params.objects("set_cache_size")
    need_stress_list = params.objects("need_stress")
    mig_total_time_list = []
    mig_downtime_list = []
    transferred_ram_list = []
    for need_stress in need_stress_list:
        for set_cache_size in set_cache_size_list:
            mig = TestMultihostMigration(test, params, env)
            mig.run()
        if len(set_cache_size_list) > 1:
            mig.check_mig_totaltime_downtime_transferred_ram()
