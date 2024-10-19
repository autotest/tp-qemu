import logging
import time

from autotest.client.shared import error, utils
from virttest import utils_misc, utils_test, virt_vm
from virttest.utils_test.qemu import migration


@error.context_aware
def run(test, params, env):
    """
    KVM multi-host migration test:

    Migration execution progress is described in documentation
    for migrate method in class MultihostMigration.

    The test procedure:
    1) starts vm on master host.
    2) query migrate capabilities
    3) a. Stress guest and ensure migration could never finish without
          auto-converge, set different values for x-cpu-throttle-initial
          and x-cpu-throttle-increment, during migration check cpu
          throttling percentage will start from $x-cpu-throttle-initial
          and increase by $x-cpu-throttle-increment, and this process
          continues until migration completes or we reach 99% throttled.
       b. load host and stress guest,ensure migration could never finish
          without auto-converge; then with auto-converge,
          migration could finish successfully; then compare the output for
          (1) default auto-converge setting (off) and (2) auto-converge
          on, the guest performance should not be effected obviously with
          auto-converge on.
       c. load host and stress guest(not load memory too much),ensure
          migration could finish with/without auto-converge; then compare
          the output for (1) default auto-converge setting (off) and (2)
          auto-converge on, the guest performance should not be effected
          obviously with auto-converge on.

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
            self.load_host_cmd = params.get("load_host_cmd")
            self.need_stress = params.get("need_stress") == "yes"
            self.need_cleanup = self.need_stress
            self.session = None
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
            if self.sub_type == "before_migrate_load_host":
                self.before_migration = self.before_migration_load_host
                self.post_migration = self.post_migration_capability_load_host
            if self.sub_type == "before_migrate_load_host_io":
                self.before_migration = self.before_migration_load_host
                self.post_migration = self.post_migration_capability_load_host_io

        def set_auto_converge(self):
            """
            enable/disable auto-converge
            """

            for i in range(1, len(self.sub_test)):
                self.set_migration_capability(self.sub_test[i], "auto-converge")
                self.capabilitys.append("auto-converge")
                self.capabilitys_state.append(self.sub_test[i])
                self.get_migration_capability(len(self.capabilitys) - 1)
                self.capabilitys.pop()
                self.capabilitys_state.pop()

        @error.context_aware
        def start_stress(self, pre_action=""):
            """
            start stress test on src before migration

            :param pre_action: run cmd before start stress
            """

            if set_auto_converge == "no":
                self.install_stressapptest()
            logging.info("Try to login guest before migration test.")
            vm = self.env.get_vm(self.params["main_vm"])
            self.session = vm.wait_for_login(timeout=self.login_timeout)
            if pre_action:
                logging.info("run cmd '%s' in guest", pre_action)
                self.session.cmd(pre_action)

            error.context("Do stress test before migration.", logging.info)
            self.session.cmd(self.bg_stress_test)

            def check_running():
                return self.session.cmd_status(self.check_running_cmd) == 0

            if self.check_running_cmd:
                if not utils_misc.wait_for(check_running, timeout=360):
                    raise error.TestFail(
                        "Failed to start '%s' in guest." % self.bg_stress_test
                    )

        @error.context_aware
        def load_host(self):
            """
            retrieve or set a process's CPU affinity
            """

            error.context("load host before migration.", logging.info)
            utils.run(self.load_host_cmd)

        @error.context_aware
        def analysis_sar_output(self, output):
            """
            analyse output of command sar after migration, get "cpu_average",
            "memory_average".

            :param output: the output of command sar during migration
            """

            output = output.splitlines()
            for index, line in enumerate(output):
                if sar_cpu_str in line:
                    cpu_average = output[index + 1].split()[2:]
                    cpu_average = list(map(float, cpu_average))
                if sar_memory_str in line:
                    memory_average_raw = output[index + 1].split()
                    memory_average = []
                    for j in range(len(memory_average_raw)):
                        if j in [3, 7]:
                            memory_average.append(memory_average_raw[j])
                    memory_average = list(map(float, memory_average))
                    break
            all_items = set(vars())
            interested_items = set(["cpu_average", "memory_average"])
            if not interested_items.issubset(all_items):
                raise error.TestFail(
                    "Failed to get '%s' '%s' in "
                    "sar output: '%s'" % (sar_cpu_str, sar_memory_str, output)
                )
            logging.info("cpu average list: %s", cpu_average)
            logging.info("memory average list: %s", memory_average)
            sar_output.append(cpu_average)
            sar_output.append(memory_average)

        @error.context_aware
        def get_sar_output(self):
            """
            get output of command sar during migration

            :param vm: vm object
            """

            error.context("Get output of command sar during migration", logging.info)
            vm = self.env.get_vm(self.params["main_vm"])
            session = vm.wait_for_login(timeout=self.login_timeout)
            while vm.is_alive():
                s, o = session.cmd_status_output(get_sar_output_cmd)  # pylint: disable=E0606
                if s != 0:
                    raise error.TestFail(
                        "Failed to get sar output in guest." "The detail is: %s" % o
                    )
            session.close()
            self.analysis_sar_output(o)

        @error.context_aware
        def check_sar_output(self):
            """
            Compare the output for (1) default auto-converge setting (off)
            and (2) auto-converge on, the guest performance should not be
            effected obviously with auto-converge on. (30% is acceptance)
            """

            logging.info("The sar output list: %s", sar_output)
            cpu_average = zip(sar_output[0], sar_output[2])
            memory_average = zip(sar_output[1], sar_output[3])
            for i in cpu_average:
                if abs(i[0] - i[1]) > 30:
                    raise error.TestFail(
                        "The guest performance should "
                        "not be effected obviously with "
                        "auto-converge on."
                    )
            for i in memory_average:
                if abs(i[0] - i[1]) > 30:
                    raise error.TestFail(
                        "The guest performance should "
                        "not be effected obviously with "
                        "auto-converge on."
                    )

        @error.context_aware
        def get_mig_cpu_throttling_percentage(self, vm):
            """
            get cpu throttling percentage during migration

            :param vm: vm object
            """

            error.context(
                "Get cpu throttling percentage during migration", logging.info
            )
            cpu_throttling_percentage = vm.monitor.info("migrate").get(
                "cpu-throttle-percentage"
            )
            logging.info(
                "The cpu throttling percentage is %s%%", cpu_throttling_percentage
            )
            return cpu_throttling_percentage

        @error.context_aware
        def check_mig_cpu_throttling_percentage(self):
            """
            check if cpu throttling percentage equal to given value
            """

            error.context(
                "check cpu throttling percentage during migration", logging.info
            )
            logging.info(
                "The cpu throttling percentage list is %s",
                cpu_throttling_percentage_list,
            )
            if (self.parameters_value[0] not in cpu_throttling_percentage_list) or (
                sum(self.parameters_value) not in cpu_throttling_percentage_list
            ):
                raise error.TestFail(
                    "The value of cpu throttling percentage "
                    "should include: %s %s"
                    % (self.parameters_value[0], sum(self.parameters_value))
                )
            if min(cpu_throttling_percentage_list) != self.parameters_value[0]:
                raise error.TestFail(
                    "The expected cpu-throttle-initial is %s,"
                    " but the actual value is %s"
                    % (self.parameters_value[0], min(cpu_throttling_percentage_list))
                )
            if max(cpu_throttling_percentage_list) > 99:
                raise error.TestFail(
                    "The expected max cpu-throttling percentage"
                    "is %s, but the actual value is %s"
                    % (99, max(cpu_throttling_percentage_list))
                )

        def thread_check_mig_cpu_throttling_percentage(self):
            """
            function, called by utils.InterruptedThread()
            """

            self.parameters_value = list(map(int, self.parameters_value))
            vm = self.env.get_vm(self.params["main_vm"])
            while self.migration_timeout:
                list_item = self.get_mig_cpu_throttling_percentage(vm)
                if list_item is not None:
                    cpu_throttling_percentage_list.append(int(list_item))
                if not cpu_throttling_percentage_list:
                    time.sleep(1)
                    self.migration_timeout -= 1
                    continue
                if max(cpu_throttling_percentage_list) >= sum(self.parameters_value):
                    break
                else:
                    time.sleep(1)
                    self.migration_timeout -= 1
            self.check_mig_cpu_throttling_percentage()

        def before_migration_capability(self, mig_data):
            """
            get migration capability (auto-converge: on/off)

            :param mig_data: Data for migration
            """

            if self.is_src:
                self.get_migration_capability()
                if self.need_set_speed:
                    self.set_migration_speed(self.max_speed)
                if set_auto_converge == "yes":
                    self.set_auto_converge()
                    self.set_migration_parameter()
                    self.get_migration_parameter()

        def before_migration_load_host(self, mig_data):
            """
            get migration capability (auto-converge: on/off)
            load host: retrieve or set a process's CPU affinity

            :param mig_data: Data for migration
            """

            if self.is_src:
                self.get_migration_capability()
                self.load_host()
                if self.need_set_speed:
                    self.set_migration_speed(self.max_speed)
                if set_auto_converge == "yes":
                    self.set_auto_converge()

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
            set auto-converge off/on during migration
            set/get parameter cpu-throttle-initial 30
            set/get parameter cpu-throttle-increment 20

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

            if set_auto_converge == "yes":
                mig_thread = utils.InterruptedThread(
                    self.thread_check_mig_cpu_throttling_percentage
                )
                mig_thread.start()
            try:
                vm.wait_for_migration(self.migration_timeout)
                logging.info("Migration completed with auto-converge on")
            except virt_vm.VMMigrateTimeoutError:
                if set_auto_converge == "yes":
                    raise error.TestFail("Migration failed with " "auto-converge on")
                else:
                    logging.info(
                        "migration would never finish with " "auto-converge off"
                    )
                    if self.need_cleanup:
                        self.clean_up(self.kill_bg_stress_cmd, vm)
                    try:
                        vm.wait_for_migration(self.migration_timeout)
                    except virt_vm.VMMigrateTimeoutError:
                        raise error.TestFail(
                            "After kill stessapptest, "
                            "migration failed with "
                            "auto-converge off"
                        )
            finally:
                if self.session:
                    self.session.close()
                vm.destroy(gracefully=False)

        @error.context_aware
        def post_migration_capability_load_host(
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
            set auto-converge off/on during migration

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

            mig_thread = utils.InterruptedThread(self.get_sar_output)
            mig_thread.start()
            try:
                vm.wait_for_migration(self.migration_timeout)
                logging.info("Migration completed with auto-converge on")
            except virt_vm.VMMigrateTimeoutError:
                if set_auto_converge == "yes":
                    raise error.TestFail("Migration failed with " "auto-converge on")
                else:
                    logging.info(
                        "migration would never finish with " "auto-converge off"
                    )
                    if self.need_cleanup:
                        self.clean_up(self.kill_bg_stress_cmd, vm)
                    try:
                        vm.wait_for_migration(self.migration_timeout)
                    except virt_vm.VMMigrateTimeoutError:
                        raise error.TestFail(
                            "After kill stessapptest, "
                            "migration failed with "
                            "auto-converge off"
                        )
            finally:
                if self.session:
                    self.session.close()
                vm.destroy(gracefully=False)
                mig_thread.join()

        @error.context_aware
        def post_migration_capability_load_host_io(
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
            set auto-converge off/on during migration

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

            mig_thread = utils.InterruptedThread(self.get_sar_output)
            mig_thread.start()
            try:
                vm.wait_for_migration(self.migration_timeout)
                logging.info(
                    "Migration completed with set auto-converge: " "%s",
                    set_auto_converge,
                )
            except virt_vm.VMMigrateTimeoutError:
                raise error.TestFail(
                    "Migration failed with set auto-converge" ": %s" % set_auto_converge
                )
            finally:
                if self.session:
                    self.session.close()
                vm.destroy(gracefully=False)
                mig_thread.join()

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
                    self.start_stress(sar_cmd_in_guest)
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

    set_auto_converge_list = params.objects("need_set_auto_converge")
    sar_log_name = params.get("sar_log_name", "")
    sar_cmd_in_guest = params.get("sar_cmd_in_guest", "")
    sar_cpu_str = params.get("sar_cpu_str", "")
    sar_memory_str = params.get("sar_memory_str", "")
    sar_output = []
    cpu_throttling_percentage_list = []
    for set_auto_converge in set_auto_converge_list:
        if sar_log_name:
            sar_log_index = str(set_auto_converge_list.index(set_auto_converge))
            tmp_sar_log_name = sar_log_name
            sar_log_name += sar_log_index
            sar_cmd_in_guest = sar_cmd_in_guest.replace(tmp_sar_log_name, sar_log_name)
            get_sar_output_cmd = params.get("get_sar_output_cmd", "tail -n 200 %s")
            get_sar_output_cmd %= sar_log_name
        mig = TestMultihostMigration(test, params, env)
        mig.run()
    if len(sar_output) == 4:
        mig.check_sar_output()
