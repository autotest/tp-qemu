import logging
import time
import threading
from autotest.client.shared import error
from autotest.client.shared import utils
from virttest import utils_test
from virttest import utils_misc
from virttest import env_process
from generic.tests import kdump
try:
    import aexpect
except ImportError:
    from virttest import aexpect


class MigrationBase(object):

    """Class that provides some general functions for multi-host migration."""

    def __setup__(self, test, params, env, srchost, dsthost):

        """initialize some public params
        """

        self.test = test
        self.params = params
        self.env = env
        self.srchost = srchost
        self.dsthost = dsthost
        self.vms = params.objects("vms")
        self.vm = self.vms[0]
        self.is_src = params["hostid"] == self.srchost
        self.pre_sub_test = params.get("pre_sub_test")
        self.post_sub_test = params.get("post_sub_test")
        self.login_before_pre_tests = params.get("login_before_pre_tests",
                                                 "no")
        self.mig_bg_command = params.get("migration_bg_command",
                                         "cd /tmp; nohup ping localhost &")
        self.mig_bg_check_command = params.get("migration_bg_check_command",
                                               "pgrep ping")
        self.mig_bg_kill_command = params.get("migration_bg_kill_command",
                                              "pkill -9 ping")
        self.migration_timeout = int(params.get("migration_timeout",
                                                "1500"))
        self.login_timeout = 480
        self.stop_migrate = False
        self.migrate_count = int(params.get("migrate_count", 1))
        self.id = {"src": self.srchost,
                   "dst": self.dsthost,
                   "type": "file_transfer"}
        self.capabilitys = params.objects("capabilitys")
        self.capabilitys_state = params.objects("capabilitys_state")
        for i in range(0, len(self.capabilitys_state)):
            if self.capabilitys_state[i].strip() == "enable":
                self.capabilitys_state[i] = True
            else:
                self.capabilitys_state[i] = False
        self.parameters = params.objects("parameters")
        self.parameters_value = params.objects("parameters_value")
        self.cache_size = params.objects("cache_size")
        self.kill_bg_stress_cmd = params.get("kill_bg_stress_cmd",
                                             "killall -9 stress")
        self.bg_stress_test = params.get("bg_stress_test")
        self.check_running_cmd = params.get("check_running_cmd")
        self.max_speed = params.get("max_migration_speed", "1000")
        self.max_speed = utils.convert_data_size(self.max_speed, "M")
        self.need_set_speed = params.get("need_set_speed", "yes") == "yes"
        self.WAIT_SHORT = 15

    @error.context_aware
    def run_pre_sub_test(self):

        """
        run sub test on src before migration
        """

        if self.is_src:
            if self.pre_sub_test:
                if self.login_before_pre_tests == "yes":
                    vm = self.env.get_vm(self.params["main_vm"])
                    vm.wait_for_login(timeout=self.login_timeout)
                error.context("Run sub test '%s' before migration on src"
                              % self.pre_sub_test, logging.info)
                utils_test.run_virt_sub_test(self.test, self.params,
                                             self.env, self.pre_sub_test)

    @error.context_aware
    def run_post_sub_test(self):

        """
        run sub test on dst after migration
        """

        if not self.is_src:
            if self.post_sub_test:
                error.context("Run sub test '%s' after migration on dst"
                              % self.post_sub_test, logging.info)
                utils_test.run_virt_sub_test(self.test, self.params,
                                             self.env, self.post_sub_test)

    def prepare_vm(self, vm_name):

        """
        Prepare, start vm and return vm.
        :param vm_name: vm name to be started.
        :return: Started VM.
        """

        self.vm_lock = threading.Lock()
        new_params = self.params.copy()
        new_params['migration_mode'] = None
        new_params['start_vm'] = 'yes'
        self.vm_lock.acquire()
        env_process.process(self.test, new_params, self.env,
                            env_process.preprocess_image,
                            env_process.preprocess_vm)
        self.vm_lock.release()
        vm = self.env.get_vm(vm_name)
        vm.wait_for_login(timeout=self.login_timeout)
        return vm

    def start_worker(self):

        """
        run background command on src before migration
        """

        if self.is_src:
            logging.info("Try to login guest before migration test.")
            vm = self.env.get_vm(self.params["main_vm"])
            session = vm.wait_for_login(timeout=self.login_timeout)
            logging.debug("Sending command: '%s'" % self.mig_bg_command)
            s, o = session.cmd_status_output(self.mig_bg_command)
            if s != 0:
                raise error.TestError("Failed to run bg cmd in guest,"
                                      " Output is '%s'." % o)
            time.sleep(5)

    def check_worker(self):

        """
        check background command on dst after migration
        """

        if not self.is_src:
            logging.info("Try to login guest after migration test.")
            vm = self.env.get_vm(self.params["main_vm"])
            serial_login = self.params.get("serial_login")
            if serial_login == "yes":
                session = vm.wait_for_serial_login(timeout=self.login_timeout)
            else:
                session = vm.wait_for_login(timeout=self.login_timeout)
            logging.info("Check the background command in the guest.")
            s, o = session.cmd_status_output(self.mig_bg_check_command)
            if s:
                raise error.TestFail("Background command not found,"
                                     " Output is '%s'." % o)
            logging.info("Kill the background command in the guest.")
            session.sendline(self.mig_bg_kill_command)
            session.close()

    @error.context_aware
    def start_worker_guest_kdump(self, mig_data, login_timeout,
                                 crash_kernel_prob_cmd,
                                 kernel_param_cmd,
                                 kdump_enable_cmd,
                                 nvcpu, crash_cmd):

        """
        force the Linux kernel to crash before migration

        :param mig_data: Data for migration
        :param login_timeout: timeout of login
        :param crash_kernel_prob_cmd: cmd for check kdump loaded
        :param kernel_param_cmd: the param add into kernel line for kdump
        :param kdump_enable_cmd: enable kdump command
        :param nvcpu: which is used to trigger a crash
        :param crash_cmd: which is triggered crash command
        """

        vm = mig_data.vms[0]
        kdump.preprocess_kdump(vm, login_timeout)
        kdump.kdump_enable(vm, vm.name, crash_kernel_prob_cmd,
                           kernel_param_cmd, kdump_enable_cmd,
                           login_timeout)
        error.context("Kdump Testing, force the Linux kernel to crash",
                      logging.info)
        kdump.crash_test(vm, nvcpu, crash_cmd, login_timeout)

    @error.context_aware
    def check_worker_kdump(self, mig_data, vmcore_chk_cmd, vmcore_incomplete):

        """
        check weather generate vmcore file after migration

        :param mig_data: Data for migration.
        :param vmcore_chk_cmd: cmd for check vmcore file
        :param vmcore_incomplete: the name of vmcore file when error
        """

        if not self.is_src:
            for vm in mig_data.vms:
                if vm.is_paused():
                    vm.resume()
                if not utils_test.qemu.guest_active(vm):
                    raise error.TestFail("Guest not active "
                                         "after migration")
                logging.info("Logging into migrated guest after "
                             "migration")
                session = vm.wait_for_login(timeout=self.login_timeout)
                error.context("Checking vmcore file in guest",
                              logging.info)
                if session is not None:
                    logging.info("kdump completed, no need ping-pong"
                                 " migration")
                    self.stop_migrate = True
                output = session.cmd_output(vmcore_chk_cmd)
                kdump.postprocess_kdump(vm, self.login_timeout)
                if not output:
                    raise error.TestFail("Could not found vmcore file")
                elif vmcore_incomplete in output.split("\n"):
                    raise error.TestError("Kdump is failed")
                logging.info("Found vmcore under /var/crash/")
                vm.destroy()

    def ping_pong_migrate(self, mig_type, sync, start_work=None,
                          check_work=None):

        """
        ping pong migration test

        :param mig_type: class MultihostMigration
        :param sync: class SyncData
        :param start_work: run sub test on src before migration
        :param check_work: run sub test on dst after migration
        """

        while True:
            if self.stop_migrate:
                break
            logging.info("ping pong migration...")
            mig_type(self.test, self.params, self.env).migrate_wait(
                [self.vm], self.srchost, self.dsthost,
                start_work=start_work, check_work=check_work)
            sync.sync(True, timeout=self.login_timeout)
            vm = self.env.get_vm(self.params["main_vm"])
            if vm.is_dead():
                self.stop_migrate = True
            elif self.migrate_count-1 == 0:
                self.stop_migrate = True
            else:
                self.dsthost, self.srchost = self.srchost, self.dsthost
                self.is_src = not self.is_src
                start_work = None

    @error.context_aware
    def get_migration_info(self, vm):

        """
        get info after migration, focus on if keys in returned disc.

        :param vm: vm object
        """

        error.context("Get 'xbzrle-cache/status/setup-time/downtime/"
                      "total-time/ram' info after migration.",
                      logging.info)
        xbzrle_cache = vm.monitor.info("migrate").get("xbzrle-cache")
        status = vm.monitor.info("migrate").get("status")
        setup_time = vm.monitor.info("migrate").get("setup-time")
        downtime = vm.monitor.info("migrate").get("downtime")
        total_time = vm.monitor.info("migrate").get("total-time")
        ram = vm.monitor.info("migrate").get("ram")
        logging.info("Migration info:\nxbzrle-cache: %s\nstatus: %s\n"
                     "setup-time: %s\ndowntime: %s\ntotal-time: "
                     "%s\nram: %s" % (xbzrle_cache, status, setup_time,
                                      downtime, total_time, ram))

    @error.context_aware
    def get_migration_capability(self, index=0):

        """
        Get the state of migrate-capability.

        :param index: the index of capabilitys list.
        """

        if self.is_src:
            for i in range(index, len(self.capabilitys)):
                error.context("Get capability '%s' state."
                              % self.capabilitys[i], logging.info)
                vm = self.env.get_vm(self.params["main_vm"])
                self.state = vm.monitor.get_migrate_capability(
                    self.capabilitys[i])
                if self.state != self.capabilitys_state[i]:
                    raise error.TestFail(
                        "The expected '%s' state: '%s',"
                        " Actual result: '%s'." % (
                            self.capabilitys[i],
                            self.capabilitys_state[i],
                            self.state))

    @error.context_aware
    def set_migration_capability(self, state, capability):

        """
        Set the capability of migrate to state.

        :param state: Bool value of capability.
        :param capability: capability which need to set.
        """

        if self.is_src:
            error.context("Set '%s' state to '%s'." % (capability, state),
                          logging.info)
            vm = self.env.get_vm(self.params["main_vm"])
            vm.monitor.set_migrate_capability(state, capability)

    @error.context_aware
    def get_migration_cache_size(self, index=0):

        """
        Get the xbzrle cache size.

        :param index: the index of cache_size list
        """

        if self.is_src:
            error.context("Try to get cache size.", logging.info)
            vm = self.env.get_vm(self.params["main_vm"])
            cache_size = vm.monitor.get_migrate_cache_size()
            error.context("Get cache size: %s" % cache_size, logging.info)
            if cache_size != int(self.cache_size[index]):
                raise error.TestFail(
                    "The expected cache size: %s,"
                    " Actual result: %s." % (self.cache_size[index],
                                             cache_size))

    @error.context_aware
    def set_migration_cache_size(self, value):

        """
        Set the cache size of migrate to value.

        :param value: the cache size to set.
        """

        if self.is_src:
            error.context("Set cache size to %s." % value, logging.info)
            vm = self.env.get_vm(self.params["main_vm"])
            vm.monitor.set_migrate_cache_size(value)

    @error.context_aware
    def get_migration_parameter(self, index=0):

        """
        Get the value of parameter.

        :param index: the index of parameters list.
        """

        if self.is_src:
            for i in range(index, len(self.parameters)):
                error.context("Get parameter '%s' value."
                              % self.parameters[i], logging.info)
                vm = self.env.get_vm(self.params["main_vm"])
                self.value = vm.monitor.get_migrate_parameter(
                    self.parameters[i])
                if int(self.value) != int(self.parameters_value[i]):
                    raise error.TestFail(
                        "The expected '%s' value: '%s',"
                        " Actual result: '%s'." % (
                            self.parameters[i],
                            self.parameters_value[i],
                            self.value))

    @error.context_aware
    def set_migration_parameter(self, index=0):

        """
        Set the value of parameter.

        :param index: the index of parameters/parameters_value list.
        """

        if self.is_src:
            for i in range(index, len(self.parameters)):
                error.context("Set '%s' value to '%s'." % (
                    self.parameters[i],
                    self.parameters_value[i]), logging.info)
                vm = self.env.get_vm(self.params["main_vm"])
                vm.monitor.set_migrate_parameter(self.parameters[i],
                                                 int(self.parameters_value[i]))

    @error.context_aware
    def set_migration_speed(self, value):

        """
        Set maximum speed (in bytes/sec) for migrations.

        :param value: Speed in bytes/sec
        """

        if self.is_src:
            error.context("Set migration speed to %s." % value, logging.info)
            vm = self.env.get_vm(self.params["main_vm"])
            vm.monitor.migrate_set_speed("%sB" % value)

    @error.context_aware
    def set_migration_downtime(self, value):

        """
        Set maximum tolerated downtime (in seconds) for migration.

        :param value: maximum downtime (in seconds)
        """

        if self.is_src:
            error.context("Set downtime to %s." % value, logging.info)
            vm = self.env.get_vm(self.params["main_vm"])
            vm.monitor.migrate_set_downtime(value)

    @error.context_aware
    def set_migration_cancel(self):

        """
        Cancel migration after it is beginning
        """

        if self.is_src:
            error.context("Cancel migration.", logging.info)
            vm = self.env.get_vm(self.params["main_vm"])
            vm.monitor.cmd("migrate_cancel")

    @error.context_aware
    def get_migration_cancelled(self):

        """
        check the migration cancelled
        """

        if self.is_src:
            vm = self.env.get_vm(self.params["main_vm"])
            o = vm.monitor.info("migrate")
            if isinstance(o, str):
                return ("Migration status: cancelled" in o or
                        "Migration status: canceled" in o)
            else:
                return (o.get("status") == "cancelled" or
                        o.get("status") == "canceled")

    @error.context_aware
    def clean_up(self, kill_bg_cmd, vm):

        """
        kill background cmd on dst after migration

        :param kill_bg_cmd: cmd for kill background test
        :param vm:  vm object
        """

        error.context("Kill the background test by '%s' in guest"
                      "." % kill_bg_cmd, logging.info)
        session = vm.wait_for_login(timeout=self.login_timeout)
        if session.cmd_status(self.check_running_cmd) != 0:
            logging.info("The background test in guest is finished, "
                         "no need to kill.")
        else:
            try:
                s, o = session.cmd_status_output(kill_bg_cmd)
                logging.info("The output after run kill command: %r" % o)
                if "No such process" in o or "not found" in o \
                        or "no running instance" in o:
                    if session.cmd_status(self.check_running_cmd) != 0:
                        logging.info("The background test in guest is "
                                     "finished before kill it.")
                elif s:
                    raise error.TestFail("Failed to kill the background"
                                         " test in guest.")
            except (aexpect.ShellStatusError, aexpect.ShellTimeoutError):
                pass
        session.close()

    @error.context_aware
    def start_stress(self):

        """
        start stress test on src before migration
        """

        logging.info("Try to login guest before migration test.")
        vm = self.env.get_vm(self.params["main_vm"])
        session = vm.wait_for_login(timeout=self.login_timeout)
        error.context("Do stress test before migration.", logging.info)
        bg = utils.InterruptedThread(
            utils_test.run_virt_sub_test,
            args=(self.test, self.params, self.env,),
            kwargs={"sub_type": self.bg_stress_test})
        bg.start()
        time.sleep(self.WAIT_SHORT)

        def check_running():
            return session.cmd_status(self.check_running_cmd) == 0

        if self.check_running_cmd:
            if not utils_misc.wait_for(check_running, timeout=360):
                raise error.TestFail("Failed to start %s in guest." %
                                     self.bg_stress_test)
