import logging
import time
import os
import re

import aexpect

from autotest.client.shared import error
from autotest.client import utils
from avocado.utils import path as avo_path
from avocado.utils import process
from avocado.core import exceptions

from virttest import error_context
from virttest import guest_agent
from virttest import utils_misc
from virttest import env_process
from virttest import data_dir


class BaseVirtTest(object):

    def __init__(self, test, params, env):
        self.test = test
        self.params = params
        self.env = env

    def initialize(self, test, params, env):
        if test:
            self.test = test
        if params:
            self.params = params
        if env:
            self.env = env

    def setup(self, test, params, env):
        if test:
            self.test = test
        if params:
            self.params = params
        if env:
            self.env = env

    def run_once(self, test, params, env):
        if test:
            self.test = test
        if params:
            self.params = params
        if env:
            self.env = env

    def before_run_once(self, test, params, env):
        pass

    def after_run_once(self, test, params, env):
        pass

    def cleanup(self, test, params, env):
        pass

    def execute(self, test, params, env):
        self.initialize(test, params, env)
        self.setup(test, params, env)
        try:
            self.before_run_once(test, params, env)
            self.run_once(test, params, env)
            self.after_run_once(test, params, env)
        finally:
            self.cleanup(test, params, env)


class QemuGuestAgentTest(BaseVirtTest):

    def __init__(self, test, params, env):
        BaseVirtTest.__init__(self, test, params, env)

        self._open_session_list = []
        self.gagent = None
        self.vm = None

    def _get_session(self, params, vm):
        if not vm:
            vm = self.vm
        vm.verify_alive()
        timeout = int(params.get("login_timeout", 360))
        session = vm.wait_for_login(timeout=timeout)
        return session

    def _cleanup_open_session(self):
        try:
            for s in self._open_session_list:
                if s:
                    s.close()
        except Exception:
            pass

    @error_context.context_aware
    def _check_ga_pkg(self, session, cmd_check_pkg):
        '''
        Check if the package is installed
        :param session: use for sending cmd
        :param cmd_check_pkg: cmd to check if ga pkg is installed
        '''
        error_context.context("Check whether qemu-ga is installed.", logging.info)
        s, o = session.cmd_status_output(cmd_check_pkg)
        return s == 0

    @error_context.context_aware
    def _check_ga_service(self, session, cmd_check_status):
        '''
        Check if the service is started.
        :param session: use for sending cmd
        :param cmd_check_status: cmd to check if ga service is started
        '''
        error_context.context("Check whether qemu-ga service is started.", logging.info)
        s, o = session.cmd_status_output(cmd_check_status)
        return s == 0

    @error_context.context_aware
    def gagent_install(self, session, vm, *args):
        if args and isinstance(args, tuple):
            gagent_install_cmd = args[0]
        else:
            self.test.error("Missing config 'gagent_install_cmd'")

        if not gagent_install_cmd:
            self.test.error("Gagent_install_cmd's value is empty.")

        error_context.context("Try to install 'qemu-guest-agent' package.",
                              logging.info)
        s, o = session.cmd_status_output(gagent_install_cmd)
        if s:
            self.test.fail("Could not install qemu-guest-agent package"
                           " in VM '%s', detail: '%s'" % (vm.name, o))

    @error_context.context_aware
    def gagent_uninstall(self, session, vm, *args):
        """
        uninstall qemu-ga pkg in guest.
        :param session: use for sending cmd
        :param vm: guest object.
        :param args: Qemu-ga pkg uninstall cmd.
        """
        if args and isinstance(args, tuple):
            gagent_uninstall_cmd = args[0]
        else:
            self.test.error("Missing config 'gagent_uninstall_cmd'")

        if not gagent_uninstall_cmd:
            self.test.error("Gagent_uninstall_cmd's value is empty.")

        error_context.context("Try to uninstall 'qemu-guest-agent' package.",
                              logging.info)
        s, o = session.cmd_status_output(gagent_uninstall_cmd)
        if s:
            self.test.fail("Could not uninstall qemu-guest-agent package "
                           "in VM '%s', detail: '%s'" % (vm.name, o))

    @error_context.context_aware
    def gagent_start(self, session, vm):
        """
        Start qemu-guest-agent in guest.
        :param session: use for sending cmd
        :param vm: Virtual machine object.
        """
        error_context.context("Try to start qemu-ga service.", logging.info)
        s, o = session.cmd_status_output(self.params["gagent_start_cmd"])
        # if start a running service, for rhel guest return code is zero,
        # for windows guest,return code is not zero
        if s and "already been started" not in o:
            self.test.fail("Could not start qemu-ga service in VM '%s',"
                           "detail: '%s'" % (vm.name, o))

    @error_context.context_aware
    def gagent_stop(self, session, vm):
        """
        Stop qemu-guest-agent in guest.
        :param session: use for sending cmd
        :param vm: Virtual machine object.
        :param args: Stop cmd.
        """
        error_context.context("Try to stop qemu-ga service.", logging.info)
        s, o = session.cmd_status_output(self.params["gagent_stop_cmd"])
        # if stop a stopped service,for rhel guest return code is zero,
        # for windows guest,return code is not zero.
        if s and "is not started" not in o:
            self.test.fail("Could not stop qemu-ga service in VM '%s', "
                           "detail: '%s'" % (vm.name, o))

    @error_context.context_aware
    def gagent_create(self, params, vm, *args):
        if self.gagent:
            return self.gagent

        error_context.context("Create a QemuAgent object.", logging.info)
        if not (args and isinstance(args, tuple) and len(args) == 2):
            raise error.TestError("Got invalid arguments for guest agent")

        gagent_serial_type = args[0]
        gagent_name = args[1]

        if gagent_serial_type == guest_agent.QemuAgent.SERIAL_TYPE_VIRTIO:
            filename = vm.get_virtio_port_filename(gagent_name)
        elif gagent_serial_type == guest_agent.QemuAgent.SERIAL_TYPE_ISA:
            filename = vm.get_serial_console_filename(gagent_name)
        else:
            raise guest_agent.VAgentNotSupportedError("Not supported serial"
                                                      " type")
        gagent = guest_agent.QemuAgent(vm, gagent_name, gagent_serial_type,
                                       filename, get_supported_cmds=True)
        self.gagent = gagent

        return self.gagent

    @error_context.context_aware
    def gagent_verify(self, params, vm):
        error_context.context("Check if guest agent work.", logging.info)

        if not self.gagent:
            raise error.TestError("Could not find guest agent object"
                                  "for VM '%s'" % vm.name)

        self.gagent.verify_responsive()
        logging.info(self.gagent.cmd("guest-info"))

    @error_context.context_aware
    def setup(self, test, params, env):
        BaseVirtTest.setup(self, test, params, env)
        start_vm = params["start_vm"]
        if (not self.vm) and (start_vm == "yes"):
            vm = self.env.get_vm(params["main_vm"])
            vm.verify_alive()
            self.vm = vm
            session = self._get_session(params, self.vm)

            if self._check_ga_pkg(session, params.get("gagent_pkg_check_cmd")):
                logging.info("qemu-ga is already installed.")
            else:
                logging.info("qemu-ga is not installed.")
                self.gagent_install(session, self.vm, *[params.get("gagent_install_cmd")])

            if self._check_ga_service(session, params.get("gagent_status_cmd")):
                logging.info("qemu-ga service is already running.")
            else:
                logging.info("qemu-ga service is not running.")
                self.gagent_start(session, self.vm)

            session.close()
            args = [params.get("gagent_serial_type"), params.get("gagent_name")]
            self.gagent_create(params, self.vm, *args)

    def run_once(self, test, params, env):
        BaseVirtTest.run_once(self, test, params, env)
        start_vm = params["start_vm"]
        if (not self.vm) and (start_vm == "yes"):
            vm = self.env.get_vm(params["main_vm"])
            vm.verify_alive()
            self.vm = vm
            self.gagent_verify(self.params, self.vm)

    def cleanup(self, test, params, env):
        self._cleanup_open_session()


class QemuGuestAgentBasicCheck(QemuGuestAgentTest):

    def __init__(self, test, params, env):
        QemuGuestAgentTest.__init__(self, test, params, env)

        self.exception_list = []

    def gagent_check_install(self, test, params, env):
        pass

    @error_context.context_aware
    def gagent_check_install_uninstall(self, test, params, env):
        """
        Repeat install/uninstall qemu-ga package in guest

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        repeats = int(params.get("repeat_times", 1))
        logging.info("Repeat install/uninstall qemu-ga pkg for %s times" % repeats)

        if not self.vm:
            self.vm = self.env.get_vm(params["main_vm"])
            self.vm.verify_alive()

        session = self._get_session(params, self.vm)
        for i in xrange(repeats):
            error_context.context("Repeat: %s/%s" % (i + 1, repeats),
                                  logging.info)
            if self._check_ga_pkg(session, params.get("gagent_pkg_check_cmd")):
                self.gagent_uninstall(session, self.vm, *[params.get("gagent_uninstall_cmd")])
                self.gagent_install(session, self.vm, *[params.get("gagent_install_cmd")])
            else:
                self.gagent_install(session, self.vm, *[params.get("gagent_install_cmd")])
                self.gagent_uninstall(session, self.vm, *[params.get("gagent_uninstall_cmd")])
        session.close()

    @error_context.context_aware
    def gagent_check_stop_start(self, test, params, env):
        """
        Repeat stop/restart qemu-ga service in guest.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        repeats = int(params.get("repeat_times", 1))
        logging.info("Repeat stop/restart qemu-ga service for %s times" % repeats)

        if not self.vm:
            self.vm = self.env.get_vm(params["main_vm"])
            self.vm.verify_alive()
        session = self._get_session(params, self.vm)
        for i in xrange(repeats):
            error_context.context("Repeat: %s/%s" % (i + 1, repeats),
                                  logging.info)
            self.gagent_stop(session, self.vm)
            time.sleep(1)
            self.gagent_start(session, self.vm)
            time.sleep(1)
            self.gagent_verify(params, self.vm)
        session.close()

    @error_context.context_aware
    def gagent_check_sync(self, test, params, env):
        """
        Execute "guest-sync" command to guest agent

        Test steps:
        1) Send "guest-sync" command in the host side.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environmen.
        """
        error_context.context("Check guest agent command 'guest-sync'", logging.info)
        self.gagent.sync()

    @error_context.context_aware
    def __gagent_check_shutdown(self, shutdown_mode):
        error_context.context("Check guest agent command 'guest-shutdown'"
                              ", shutdown mode '%s'" % shutdown_mode, logging.info)
        if not self.env or not self.params:
            raise error.TestError("You should run 'setup' method before test")

        if not (self.vm and self.vm.is_alive()):
            vm = self.env.get_vm(self.params["main_vm"])
            vm.verify_alive()
            self.vm = vm
        self.gagent.shutdown(shutdown_mode)

    def __gagent_check_serial_output(self, pattern):
        start_time = time.time()
        while (time.time() - start_time) < self.vm.REBOOT_TIMEOUT:
            if pattern in self.vm.serial_console.get_output():
                return True
        return False

    def gagent_check_powerdown(self, test, params, env):
        """
        Shutdown guest with guest agent command "guest-shutdown"

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environmen.
        """
        self.__gagent_check_shutdown(self.gagent.SHUTDOWN_MODE_POWERDOWN)
        if not utils_misc.wait_for(self.vm.is_dead, self.vm.REBOOT_TIMEOUT):
            raise error.TestFail("Could not shutdown VM via guest agent'")

    @error_context.context_aware
    def gagent_check_reboot(self, test, params, env):
        """
        Reboot guest with guest agent command "guest-shutdown"

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environmen.
        """
        self.__gagent_check_shutdown(self.gagent.SHUTDOWN_MODE_REBOOT)
        pattern = params["gagent_guest_reboot_pattern"]
        error_context.context("Verify serial output has '%s'" % pattern)
        rebooted = self.__gagent_check_serial_output(pattern)
        if not rebooted:
            raise error.TestFail("Could not reboot VM via guest agent")
        error_context.context("Try to re-login to guest after reboot")
        try:
            session = self._get_session(self.params, None)
            session.close()
        except Exception, detail:
            raise error.TestFail("Could not login to guest,"
                                 " detail: '%s'" % detail)

    @error_context.context_aware
    def gagent_check_halt(self, test, params, env):
        """
        Halt guest with guest agent command "guest-shutdown"

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environmen.
        """
        self.__gagent_check_shutdown(self.gagent.SHUTDOWN_MODE_HALT)
        pattern = params["gagent_guest_shutdown_pattern"]
        error_context.context("Verify serial output has '%s'" % pattern)
        halted = self.__gagent_check_serial_output(pattern)
        if not halted:
            raise error.TestFail("Could not halt VM via guest agent")
        # Since VM is halted, force shutdown it.
        try:
            self.vm.destroy(gracefully=False)
        except Exception, detail:
            logging.warn("Got an exception when force destroying guest:"
                         " '%s'", detail)

    @error_context.context_aware
    def gagent_check_sync_delimited(self, test, params, env):
        """
        Execute "guest-sync-delimited" command to guest agent

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        error_context.context("Check guest agent command 'guest-sync-delimited'",
                              logging.info)
        self.gagent.sync("guest-sync-delimited")

    @error_context.context_aware
    def _gagent_verify_password(self, vm, new_password):
        """
        check if the password  works well for the specific user
        """
        vm.wait_for_login(password=new_password)

    @error_context.context_aware
    def gagent_check_set_user_password(self, test, params, env):
        """
        Execute "guest-set-user-password" command to guest agent
        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        old_password = params.get("password", "")
        new_password = params.get("new_password", "123456")
        ga_username = params.get("ga_username", "root")
        crypted = params.get("crypted", "") == "yes"
        error_context.context("Change guest's password.")
        try:
            self.gagent.set_user_password(new_password, crypted, ga_username)
            error_context.context("Check if the guest could be login by new password",
                                  logging.info)
            self._gagent_verify_password(self.vm, new_password)

        except guest_agent.VAgentCmdError:
            test.fail("Failed to set the new password for guest")

        finally:
            error_context.context("Reset back the password of guest", logging.info)
            self.gagent.set_user_password(old_password, username=ga_username)

    @error_context.context_aware
    def gagent_check_get_vcpus(self, test, params, env):
        """
        Execute "guest-set-vcpus" command to guest agent
        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        self.gagent.get_vcpus()

    @error_context.context_aware
    def gagent_check_set_vcpus(self, test, params, env):
        """
        Execute "guest-set-vcpus" command to guest agent
        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        error_context.context("get the cpu number of the testing guest")
        vcpus_info = self.gagent.get_vcpus()
        vcpus_num = len(vcpus_info)
        error_context.context("the vcpu number:%d" % vcpus_num, logging.info)
        if vcpus_num < 2:
            raise error.TestNAError("the vpus number of guest should be more"
                                    " than 1")
        vcpus_info[vcpus_num - 1]["online"] = False
        del vcpus_info[vcpus_num - 1]["can-offline"]
        action = {'vcpus': [vcpus_info[vcpus_num - 1]]}
        self.gagent.set_vcpus(action)
        # Check if the result is as expected
        vcpus_info = self.gagent.get_vcpus()
        if vcpus_info[vcpus_num - 1]["online"] is not False:
            raise error.TestFail("the vcpu status is not changed as expected")

    @error_context.context_aware
    def gagent_check_get_time(self, test, params, env):
        """
        Execute "guest-get-time" command to guest agent
        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        timeout = float(params.get("login_timeout", 240))
        session = self.vm.wait_for_login(timeout=timeout)
        get_guest_time_cmd = params["get_guest_time_cmd"]
        error_context.context("get the time of the guest", logging.info)
        nanoseconds_time = self.gagent.get_time()
        error_context.context("the time get by guest-get-time is '%d' "
                              % nanoseconds_time, logging.info)
        guest_time = session.cmd_output(get_guest_time_cmd)
        if not guest_time:
            raise error.TestError("can't get the guest time for contrast")
        error_context.context("the time get inside guest by shell cmd is '%d' "
                              % int(guest_time), logging.info)
        delta = abs(int(guest_time) - nanoseconds_time / 1000000000)
        if delta > 3:
            raise error.TestFail("the time get by guest agent is not the same "
                                 "with that by time check cmd inside guest")

    @error_context.context_aware
    def gagent_check_set_time(self, test, params, env):
        """
        Execute "guest-set-time" command to guest agent
        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        timeout = float(params.get("login_timeout", 240))
        session = self.vm.wait_for_login(timeout=timeout)
        get_guest_time_cmd = params["get_guest_time_cmd"]
        error_context.context("get the time of the guest", logging.info)
        guest_time_before = session.cmd_output(get_guest_time_cmd)
        if not guest_time_before:
            raise error.TestError("can't get the guest time for contrast")
        error_context.context("the time before being moved back into past  is '%d' "
                              % int(guest_time_before), logging.info)
        # Need to move the guest time one week into the past
        target_time = (int(guest_time_before) - 604800) * 1000000000
        self.gagent.set_time(target_time)
        guest_time_after = session.cmd_output(get_guest_time_cmd)
        error_context.context("the time after being moved back into past  is '%d' "
                              % int(guest_time_after), logging.info)
        delta = abs(int(guest_time_after) - target_time / 1000000000)
        if delta > 3:
            raise error.TestFail("the time set for guest is not the same "
                                 "with target")
        # Set the system time from the hwclock
        if params["os_type"] != "windows":
            move_time_cmd = params["move_time_cmd"]
            session.cmd("hwclock -w")
            guest_hwclock_after_set = session.cmd_output("date +%s")
            error_context.context("hwclock is '%d' " % int(guest_hwclock_after_set),
                                  logging.info)
            session.cmd(move_time_cmd)
            time_after_move = session.cmd_output("date +%s")
            error_context.context("the time after move back is '%d' "
                                  % int(time_after_move), logging.info)
            self.gagent.set_time()
            guest_time_after_reset = session.cmd_output(get_guest_time_cmd)
            error_context.context("the time after being reset is '%d' "
                                  % int(guest_time_after_reset), logging.info)
            guest_hwclock = session.cmd_output("date +%s")
            error_context.context("hwclock for compare is '%d' " % int(guest_hwclock),
                                  logging.info)
            delta = abs(int(guest_time_after_reset) - int(guest_hwclock))
            if delta > 3:
                raise error.TestFail("The guest time can't be set from hwclock"
                                     " on host")

    @error_context.context_aware
    def _get_mem_used(self, session, cmd):
        """
        get memory usage of the process

        :param session: use for sending cmd
        :param cmd: get details of the process
        """

        output = session.cmd_output(cmd)
        logging.info("The process details: %s" % output)
        try:
            memory_usage = int(output.split(" ")[-2].replace(",", ""))
            return memory_usage
        except Exception:
            raise exceptions.TestError("Get invalid memory usage by "
                                       "cmd '%s' (%s)" % (cmd, output))

    @error_context.context_aware
    def gagent_check_memory_leak(self, test, params, env):
        """
        repeat execute "guest-info" command to guest agent, check memory
        usage of the qemu-ga

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """

        timeout = float(params.get("login_timeout", 240))
        test_command = params.get("test_command", "guest-info")
        memory_usage_cmd = params.get("memory_usage_cmd",
                                      "tasklist | findstr /I qemu-ga.exe")
        session = self.vm.wait_for_login(timeout=timeout)
        error_context.context("get the memory usage of qemu-ga before run '%s'" %
                              test_command, logging.info)
        memory_usage_before = self._get_mem_used(session, memory_usage_cmd)
        session.close()
        repeats = int(params.get("repeats", 1))
        for i in range(repeats):
            error_context.context("execute '%s' %s times" % (test_command, i + 1),
                                  logging.info)
            return_msg = self.gagent.guest_info()
            logging.info(str(return_msg))
        self.vm.verify_alive()
        error_context.context("get the memory usage of qemu-ga after run '%s'" %
                              test_command, logging.info)
        session = self.vm.wait_for_login(timeout=timeout)
        memory_usage_after = self._get_mem_used(session, memory_usage_cmd)
        session.close()
        # less than 500K is acceptable.
        if memory_usage_after - memory_usage_before > 500:
            raise error.TestFail("The memory usages are different, "
                                 "before run command is %skb and after"
                                 " run command is %skb" % (memory_usage_before,
                                                           memory_usage_after))

    @error_context.context_aware
    def gagent_check_fstrim(self, test, params, env):
        """
        Execute "guest-fstrim" command to guest agent
        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.

        """
        def get_host_scsi_disk():
            """
            Get latest scsi disk which enulated by scsi_debug module
            Return the device name and the id in host
            """
            scsi_disk_info = process.system_output(
                avo_path.find_command('lsscsi'), shell=True).splitlines()
            scsi_debug = [_ for _ in scsi_disk_info if 'scsi_debug' in _][-1]
            scsi_debug = scsi_debug.split()
            host_id = scsi_debug[0][1:-1]
            device_name = scsi_debug[-1]
            return (host_id, device_name)

        def get_guest_discard_disk(session):
            """
            Get disk without partitions in guest.
            """
            list_disk_cmd = "ls /dev/[sh]d*|sed 's/[0-9]//p'|uniq -u"
            disk = session.cmd_output(list_disk_cmd).splitlines()[0]
            return disk

        def get_provisioning_mode(device, host_id):
            """
            Get disk provisioning mode, value usually is 'writesame_16',
            depends on params for scsi_debug module.
            """
            device_name = os.path.basename(device)
            path = "/sys/block/%s/device/scsi_disk" % device_name
            path += "/%s/provisioning_mode" % host_id
            return utils.read_one_line(path).strip()

        def get_allocation_bitmap():
            """
            get block allocation bitmap
            """
            path = "/sys/bus/pseudo/drivers/scsi_debug/map"
            try:
                return utils.read_one_line(path).strip()
            except IOError:
                logging.warn("could not get bitmap info, path '%s' is "
                             "not exist", path)
            return ""

        for vm in env.get_all_vms():
            if vm:
                vm.destroy()
                env.unregister_vm(vm.name)
        host_id, disk_name = get_host_scsi_disk()
        provisioning_mode = get_provisioning_mode(disk_name, host_id)
        logging.info("Current provisioning_mode = '%s'", provisioning_mode)
        bitmap = get_allocation_bitmap()
        if bitmap:
            logging.debug("block allocation bitmap: %s" % bitmap)
            raise error.TestError("block allocation bitmap"
                                  " not empty before test.")
        vm_name = params["main_vm"]
        test_image = "scsi_debug"
        params["start_vm"] = "yes"
        params["image_name_%s" % test_image] = disk_name
        params["image_format_%s" % test_image] = "raw"
        params["image_raw_device_%s" % test_image] = "yes"
        params["force_create_image_%s" % test_image] = "no"
        params["drive_format_%s" % test_image] = "scsi-block"
        params["drv_extra_params_%s" % test_image] = "discard=on"
        params["images"] = " ".join([params["images"], test_image])

        error_context.context("boot guest with disk '%s'" % disk_name, logging.info)
        env_process.preprocess_vm(test, params, env, vm_name)

        self.setup(test, params, env)
        timeout = float(params.get("login_timeout", 240))
        session = self.vm.wait_for_login(timeout=timeout)
        device_name = get_guest_discard_disk(session)

        error_context.context("format disk '%s' in guest" % device_name, logging.info)
        format_disk_cmd = params["format_disk_cmd"]
        format_disk_cmd = format_disk_cmd.replace("DISK", device_name)
        session.cmd(format_disk_cmd)

        error_context.context("mount disk with discard options '%s'" % device_name,
                              logging.info)
        mount_disk_cmd = params["mount_disk_cmd"]
        mount_disk_cmd = mount_disk_cmd.replace("DISK", device_name)
        session.cmd(mount_disk_cmd)

        error_context.context("write the disk with dd command", logging.info)
        write_disk_cmd = params["write_disk_cmd"]
        session.cmd(write_disk_cmd)

        error_context.context("Delete the file created before on disk", logging.info)
        delete_file_cmd = params["delete_file_cmd"]
        session.cmd(delete_file_cmd)

        # check the bitmap before trim
        bitmap_before_trim = get_allocation_bitmap()
        if not re.match(r"\d+-\d+", bitmap_before_trim):
            raise error.TestFail("didn't get the bitmap of the target disk")
        error_context.context("the bitmap_before_trim is %s" % bitmap_before_trim,
                              logging.info)
        total_block_before_trim = abs(sum([eval(i) for i in
                                           bitmap_before_trim.split(',')]))
        error_context.context("the total_block_before_trim is %d"
                              % total_block_before_trim, logging.info)

        error_context.context("execute the guest-fstrim cmd", logging.info)
        self.gagent.fstrim()

        # check the bitmap after trim
        bitmap_after_trim = get_allocation_bitmap()
        if not re.match(r"\d+-\d+", bitmap_after_trim):
            raise error.TestFail("didn't get the bitmap of the target disk")
        error_context.context("the bitmap_after_trim is %s" % bitmap_after_trim,
                              logging.info)
        total_block_after_trim = abs(sum([eval(i) for i in
                                          bitmap_after_trim.split(',')]))
        error_context.context("the total_block_after_trim is %d"
                              % total_block_after_trim, logging.info)

        if total_block_after_trim > total_block_before_trim:
            raise error.TestFail("the bitmap_after_trim is lager, the command"
                                 " guest-fstrim may not work")
        if self.vm:
            self.vm.destroy()

    @error_context.context_aware
    def gagent_check_get_interfaces(self, test, params, env):
        """
        Execute "guest-network-get-interfaces" command to guest agent
        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        def find_interface_by_name(interface_list, target_interface):
            """
            find the specific network interface in the interface list return
            by guest agent. return True if find successfully
            """
            for interface in interface_list:
                if "target_interface" == interface["name"]:
                    return True
            return False
        session = self._get_session(params, None)

        # check if the cmd "guest-network-get-interfaces" work
        ret = self.gagent.get_network_interface()
        if not find_interface_by_name(ret, "lo"):
            error.TestFail("didn't find 'lo' interface in the return value")

        error_context.context("set down the interface: lo", logging.info)
        down_interface_cmd = "ip link set lo down"
        session.cmd(down_interface_cmd)

        interfaces_pre_add = self.gagent.get_network_interface()

        error_context.context("add the new device bridge in guest", logging.info)
        add_brige_cmd = "ip link add link lo name lo_brige type bridge"
        session.cmd(add_brige_cmd)

        interfaces_after_add = self.gagent.get_network_interface()

        bridge_list = [_ for _ in interfaces_after_add if _ not in
                       interfaces_pre_add]
        if (len(bridge_list) != 1) or \
           ("lo_brige" != bridge_list[0]["name"]):
            error.TestFail("the interface list info after interface was down"
                           " was not as expected")

    @error_context.context_aware
    def _action_before_fsfreeze(self, *args):
        session = self._get_session(self.params, None)
        self._open_session_list.append(session)

    @error_context.context_aware
    def _action_after_fsfreeze(self, *args):
        error_context.context("Verfiy FS is frozen in guest.")
        if not isinstance(args, tuple):
            return

        if not self._open_session_list:
            raise error.TestError("Could not find any opened session")
        # Use the last opened session to send cmd.
        session = self._open_session_list[-1]
        try:
            session.cmd(self.params["gagent_fs_test_cmd"])
        except aexpect.ShellTimeoutError:
            logging.debug("FS freeze successfully.")
        else:
            raise error.TestFail("FS freeze failed, guest still can"
                                 " write file")

    @error_context.context_aware
    def _action_before_fsthaw(self, *args):
        pass

    @error_context.context_aware
    def _action_after_fsthaw(self, *args):
        pass

    @error_context.context_aware
    def gagent_check_fsfreeze(self, test, params, env):
        """
        Test guest agent commands "guest-fsfreeze-freeze/status/thaw"

        Test steps:
        1) Check the FS is thawed.
        2) Freeze the FS.
        3) Check the FS is frozen from both guest agent side and guest os side.
        4) Thaw the FS.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environmen.
        """
        error.base_context("Check guest agent command 'guest-fsfreeze-freeze'",
                           logging.info)
        error_context.context("Verify FS is thawed and freeze the FS.")

        try:
            expect_status = self.gagent.FSFREEZE_STATUS_THAWED
            self.gagent.verify_fsfreeze_status(expect_status)
        except guest_agent.VAgentFreezeStatusError:
            # Thaw guest FS if the fs status is incorrect.
            self.gagent.fsthaw(check_status=False)

        self._action_before_fsfreeze(test, params, env)
        self.gagent.fsfreeze()
        try:
            self._action_after_fsfreeze(test, params, env)

            # Next, thaw guest fs.
            self._action_before_fsthaw(test, params, env)
            error_context.context("Thaw the FS.")
            self.gagent.fsthaw()
        except Exception:
            # Thaw fs finally, avoid problem in following cases.
            try:
                self.gagent.fsthaw(check_status=False)
            except Exception, detail:
                # Ignore exception for this thaw action.
                logging.warn("Finally failed to thaw guest fs,"
                             " detail: '%s'", detail)
            raise

        # Finally, do something after thaw.
        self._action_after_fsthaw(test, params, env)

    def run_once(self, test, params, env):
        QemuGuestAgentTest.run_once(self, test, params, env)

        gagent_check_type = self.params["gagent_check_type"]
        chk_type = "gagent_check_%s" % gagent_check_type
        if hasattr(self, chk_type):
            func = getattr(self, chk_type)
            func(test, params, env)
        else:
            raise error.TestError("Could not find matching test, check your"
                                  " config file")


class QemuGuestAgentBasicCheckWin(QemuGuestAgentBasicCheck):

    """
    Qemu guest agent test class for windows guest.
    """

    @error_context.context_aware
    def setup_gagent_in_host(self, session, params, vm):
        error_context.context("download qemu-ga.msi to host", logging.info)
        deps = params["deps"]
        gagent_download_cmd = params["gagent_download_cmd"]
        if deps == "yes":
            deps_dir = data_dir.get_deps_dir("windows_ga_install")
            gagent_download_cmd = gagent_download_cmd % deps_dir
        utils.run(gagent_download_cmd,
                  float(params.get("login_timeout", 360)))
        gagent_host_path = params["gagent_host_path"]
        if not os.path.exists(gagent_host_path):
            raise error.TestFail("qemu-ga install program is not exist, maybe "
                                 "the program is not successfully downloaded ")
        gagent_guest_dir = params["gagent_guest_dir"]
#        gagent_remove_service_cmd = params["gagent_remove_service_cmd"]
        s, o = session.cmd_status_output("mkdir %s" % gagent_guest_dir)
        if bool(s) and str(s) != "1":
            raise error.TestError("Could not create qemu-ga directory in "
                                  "VM '%s', detail: '%s'" % (vm.name, o))
        error_context.context("Copy qemu guest agent program to guest", logging.info)
        vm.copy_files_to(gagent_host_path, gagent_guest_dir)

    @error_context.context_aware
    def setup(self, test, params, env):
        BaseVirtTest.setup(self, test, params, env)
        start_vm = params["start_vm"]
        if (not self.vm) and (start_vm == "yes"):
            vm = self.env.get_vm(params["main_vm"])
            vm.verify_alive()
            self.vm = vm
            session = self._get_session(params, self.vm)

            if self._check_ga_pkg(session, params.get("gagent_pkg_check_cmd")):
                logging.info("qemu-ga is already installed.")
            else:
                logging.info("qemu-ga is not installed.")
                self.setup_gagent_in_host(session, params, self.vm)
                self.gagent_install(session, self.vm, *[params.get("gagent_install_cmd")])

            if self._check_ga_service(session, params.get("gagent_status_cmd")):
                logging.info("qemu-ga service is already running.")
            else:
                logging.info("qemu-ga service is not running.")
                self.gagent_start(session, self.vm)

            session.close()
            args = [params.get("gagent_serial_type"), params.get("gagent_name")]
            self.gagent_create(params, vm, *args)


def run(test, params, env):
    """
    Test qemu guest agent, this case will:
    1) Start VM with virtio serial port.
    2) Install qemu-guest-agent package in guest.
    3) Run some basic test for qemu guest agent.

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environmen.
    """
    if params["os_type"] == "windows":
        gagent_test = QemuGuestAgentBasicCheckWin(test, params, env)
    else:
        gagent_test = QemuGuestAgentBasicCheck(test, params, env)

    gagent_test.execute(test, params, env)
