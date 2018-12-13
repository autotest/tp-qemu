import logging
import time
import os
import re
import base64

import aexpect

from avocado.utils import genio
from avocado.utils import path as avo_path
from avocado.utils import process
from avocado.core import exceptions

from virttest import error_context
from virttest import guest_agent
from virttest import utils_misc
from virttest import utils_disk
from virttest import env_process


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
        start_vm = self.params["start_vm"]
        self.start_vm = start_vm
        if self.start_vm == "yes":
            vm = self.env.get_vm(params["main_vm"])
            vm.verify_alive()
            self.vm = vm

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
        self.gagent_install_cmd = params.get("gagent_install_cmd")
        self.gagent_uninstall_cmd = params.get("gagent_uninstall_cmd")

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
    def gagent_install(self, session, vm):
        """
        install qemu-ga pkg in guest.
        :param session: use for sending cmd
        :param vm: guest object.
        """
        error_context.context("Try to install 'qemu-guest-agent' package.",
                              logging.info)
        s, o = session.cmd_status_output(self.gagent_install_cmd)
        if s:
            self.test.fail("Could not install qemu-guest-agent package"
                           " in VM '%s', detail: '%s'" % (vm.name, o))

    @error_context.context_aware
    def gagent_uninstall(self, session, vm):
        """
        uninstall qemu-ga pkg in guest.
        :param session: use for sending cmd
        :param vm: guest object.
        """
        error_context.context("Try to uninstall 'qemu-guest-agent' package.",
                              logging.info)
        s, o = session.cmd_status_output(self.gagent_uninstall_cmd)
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
            self.test.error("Got invalid arguments for guest agent")

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
            self.test.error("Could not find guest agent object "
                            "for VM '%s'" % vm.name)

        self.gagent.verify_responsive()
        logging.info(self.gagent.cmd("guest-info"))

    @error_context.context_aware
    def setup(self, test, params, env):
        BaseVirtTest.setup(self, test, params, env)
        if self.start_vm == "yes":
            session = self._get_session(params, self.vm)
            if self._check_ga_pkg(session, params.get("gagent_pkg_check_cmd")):
                logging.info("qemu-ga is already installed.")
            else:
                logging.info("qemu-ga is not installed.")
                self.gagent_install(session, self.vm)

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
        if self.start_vm == "yes":
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
        for i in range(repeats):
            error_context.context("Repeat: %s/%s" % (i + 1, repeats),
                                  logging.info)
            if self._check_ga_pkg(session, params.get("gagent_pkg_check_cmd")):
                self.gagent_uninstall(session, self.vm)
                self.gagent_install(session, self.vm)
            else:
                self.gagent_install(session, self.vm)
                self.gagent_uninstall(session, self.vm)
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
        for i in range(repeats):
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
            self.test.error("You should run 'setup' method before test")

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
            test.fail("Could not shutdown VM via guest agent'")

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
            test.fail("Could not reboot VM via guest agent")
        error_context.context("Try to re-login to guest after reboot")
        try:
            session = self._get_session(self.params, None)
            session.close()
        except Exception as detail:
            test.fail("Could not login to guest"
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
            test.fail("Could not halt VM via guest agent")
        # Since VM is halted, force shutdown it.
        try:
            self.vm.destroy(gracefully=False)
        except Exception as detail:
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
            test.error("the vpus number of guest should be more than 1")
        vcpus_info[vcpus_num - 1]["online"] = False
        del vcpus_info[vcpus_num - 1]["can-offline"]
        action = {'vcpus': [vcpus_info[vcpus_num - 1]]}
        self.gagent.set_vcpus(action)
        # Check if the result is as expected
        vcpus_info = self.gagent.get_vcpus()
        if vcpus_info[vcpus_num - 1]["online"] is not False:
            test.fail("the vcpu status is not changed as expected")

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
            test.error("can't get the guest time for contrast")
        error_context.context("the time get inside guest by shell cmd is '%d' "
                              % int(guest_time), logging.info)
        delta = abs(int(guest_time) - nanoseconds_time / 1000000000)
        if delta > 3:
            test.fail("the time get by guest agent is not the same "
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
            test.error("can't get the guest time for contrast")
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
            test.fail("the time set for guest is not the same with target")
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
                test.fail("The guest time can't be set from hwclock on host")

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
            test.fail("The memory usages are different, "
                      "before run command is %skb and "
                      "after run command is %skb" % (memory_usage_before,
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
                avo_path.find_command('lsscsi'), shell=True)
            scsi_disk_info = scsi_disk_info.decode().splitlines()
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
            return genio.read_one_line(path).strip()

        def get_allocation_bitmap():
            """
            get block allocation bitmap
            """
            path = "/sys/bus/pseudo/drivers/scsi_debug/map"
            try:
                return genio.read_one_line(path).strip()
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
            test.error("block allocation bitmap not empty before test.")
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

        self.initialize(test, params, env)
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
            test.fail("didn't get the bitmap of the target disk")
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
            test.fail("didn't get the bitmap of the target disk")
        error_context.context("the bitmap_after_trim is %s" % bitmap_after_trim,
                              logging.info)
        total_block_after_trim = abs(sum([eval(i) for i in
                                          bitmap_after_trim.split(',')]))
        error_context.context("the total_block_after_trim is %d"
                              % total_block_after_trim, logging.info)

        if total_block_after_trim > total_block_before_trim:
            test.fail("the bitmap_after_trim is lager, the command"
                      "guest-fstrim may not work")
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
                if target_interface == interface["name"]:
                    return True
            return False
        session = self._get_session(params, None)

        # check if the cmd "guest-network-get-interfaces" work
        ret = self.gagent.get_network_interface()
        if not find_interface_by_name(ret, "lo"):
            test.fail("didn't find 'lo' interface in the return value")

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
            test.fail("the interface list info after interface was down "
                      "was not as expected")

    @error_context.context_aware
    def _action_before_fsfreeze(self, *args):
        session = self._get_session(self.params, None)
        self._open_session_list.append(session)

    @error_context.context_aware
    def _action_after_fsfreeze(self, *args):
        error_context.context("Verfiy FS is frozen in guest.", logging.info)

        if not self._open_session_list:
            self.test.error("Could not find any opened session")
        # Use the last opened session to send cmd.
        session = self._open_session_list[-1]

        try:
            session.cmd(self.params["gagent_fs_test_cmd"])
        except aexpect.ShellTimeoutError:
            logging.info("FS is frozen as expected,can't write in guest.")
        else:
            self.test.fail("FS is not frozen,still can write in guest.")

    def gagent_check_reboot_shutdown(self, test, params, env):
        """
        Send "shutdown,reboot" command to guest agent
        after FS freezed
        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        gagent = self.gagent
        gagent.fsfreeze()
        try:
            for mode in (gagent.SHUTDOWN_MODE_POWERDOWN, gagent.SHUTDOWN_MODE_REBOOT):
                try:
                    gagent.shutdown(mode)
                except guest_agent.VAgentCmdError as detail:
                    if not re.search('guest-shutdown has been disabled', str(detail)):
                        test.fail("This is not the desired information: ('%s')" % str(detail))
                else:
                    test.fail("agent shutdown command shouldn't succeed for freeze FS")
        finally:
            try:
                gagent.fsthaw(check_status=False)
            except Exception:
                pass

    @error_context.context_aware
    def _action_before_fsthaw(self, *args):
        pass

    @error_context.context_aware
    def _action_after_fsthaw(self, *args):
        error_context.context("Verify FS is thawed in guest.", logging.info)

        if not self._open_session_list:
            session = self._get_session(self.params, None)
            self._open_session_list.append(session)
        # Use the last opened session to send cmd.
        session = self._open_session_list[-1]

        try:
            session.cmd(self.params["gagent_fs_test_cmd"])
        except aexpect.ShellTimeoutError:
            self.test.fail("FS is not thawed, still can't write in guest.")
        else:
            logging.info("FS is thawed as expected, can write in guest.")

    @error_context.context_aware
    def gagent_check_fsfreeze(self, test, params, env):
        """
        Test guest agent commands "guest-fsfreeze-freeze/status/thaw"

        Test steps:
        1) Check the FS is thawed.
        2) Freeze the FS.
        3) Check the FS is frozen from both guest agent side and guest os side.
        4) Thaw the FS.
        5) Check the FS is unfrozen from both guest agent side and guest os side.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environmen.
        """
        error_context.context("Check guest agent command "
                              "'guest-fsfreeze-freeze/thaw'",
                              logging.info)
        try:
            expect_status = self.gagent.FSFREEZE_STATUS_THAWED
            self.gagent.verify_fsfreeze_status(expect_status)
        except guest_agent.VAgentFreezeStatusError:
            # Thaw guest FS if the fs status is incorrect.
            self.gagent.fsthaw(check_status=False)

        self._action_before_fsfreeze()
        error_context.context("Freeze the FS.", logging.info)
        self.gagent.fsfreeze()
        try:
            self._action_after_fsfreeze()
            # Next, thaw guest fs.
            self._action_before_fsthaw()
            error_context.context("Thaw the FS.", logging.info)
            self.gagent.fsthaw()
        except Exception:
            # Thaw fs finally, avoid problem in following cases.
            try:
                self.gagent.fsthaw(check_status=False)
            except Exception as detail:
                # Ignore exception for this thaw action.
                logging.warn("Finally failed to thaw guest fs,"
                             " detail: '%s'", detail)
            raise

        self._action_after_fsthaw()

    @error_context.context_aware
    def gagent_check_guest_file(self, test, params, env):
        """
        Test guest agent commands "guest-file-open/write/flush/
        seek/read/close".

        Test steps:
        1) set file related cmd to qemu-ga white list(linux guest only)
        2) read guest file which is created in guest.
          a. create file in guest and write "hello world" to it.
          b. open and read file with mode "r".
          c. close file.
        3) create new file with mode "w" and write to it.
          a. open a file with mode "w".
          b. write "hello world" to guest file with file_write cmd.
          c. flush the data to disk.
          d. check file content from guest.
        4) seek one position and read file content.
          a. seek from the file beginning position and offset is 0
             ,and read all content
          b. seek from the file beginning position and offset is 0,
             read two bytes.
          c. seek from current position and offset is 2,read 5 bytes.
          d. seek from the file end and offset is -5,read 3 bytes.
        5) close file

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environmen.
        """

        def _read_check(ret_handle, content, count=None):
            """
            Read file and check if the content read is correct.

            :param ret_handle: file handle returned by guest-file-open
            :param count: maximum number of bytes to read
            :param content: expected content
            """
            logging.info("Read content and do check.")
            ret_read = self.gagent.guest_file_read(ret_handle, count=count)
            content_read = base64.b64decode(ret_read["buf-b64"]).decode()
            if not content_read.strip() == content.strip():
                test.fail("The read content is '%s'; the real content is '%s'."
                          % (content_read, content))

        def _change_bl():
            """
            As file related cmd is in blacklist at default,so need to change.
            Now only linux guest has this behavior,but still leave interface
            for windows guest.
            """
            if params.get("os_type") == "linux":
                output = session.cmd_output(params["cmd_verify"])
                if output == "":
                    logging.info("Guest-file related cmds are already "
                                 "in white list.")
                    return

                session.cmd(params["cmd_change_black"])
                output = session.cmd_output(params["cmd_verify"])
                if not output == "":
                    test.fail("Failed to change guest-file related cmd to "
                              "white list, the output is %s" % output)

                s, o = session.cmd_status_output(params["gagent_restart_cmd"])
                if s:
                    test.fail("Could not restart qemu-ga in VM after changing"
                              " list, detail: %s" % o)

        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)

        error_context.context("Change guest-file related cmd to white list.")
        _change_bl()

        error_context.context("Read guest file with file-read cmd.",
                              logging.info)
        # read guest file which are already created in guest.
        logging.info("Create file in guest.")
        ranstr = utils_misc.generate_random_string(5)
        tmp_file = "%s%s" % (params["file_path"], ranstr)
        content = "hello world"
        session.cmd("echo %s > %s" % (content, tmp_file))

        logging.info("Open and read the guest file.")
        ret_handle = int(self.gagent.guest_file_open(tmp_file))
        _read_check(ret_handle, content)

        logging.info("Close the opened file.")
        self.gagent.guest_file_close(ret_handle)

        # create a new file by agent.
        error_context.context("Create new file with mode 'w' and write to it",
                              logging.info)
        ranstr = utils_misc.generate_random_string(5)
        tmp_file = "%s%s" % (params["file_path"], ranstr)
        ret_handle = int(self.gagent.guest_file_open(tmp_file, mode="w+"))

        logging.info("Write content to the file.")
        content = "%s\n" % content

        self.gagent.guest_file_write(ret_handle, content)
        self.gagent.guest_file_flush(ret_handle)

        logging.info("check file content from guest.")
        cmd_check_file = "%s %s" % (params["cmd_read"], tmp_file)
        status, output = session.cmd_status_output(cmd_check_file)
        if status:
            test.error("Read file content cmd failed, the output is %s."
                       % output)
        elif output.strip() == content.strip():
            logging.info("Succeed to write the content.")
        else:
            test.fail("Write content failed, the content read from guest is "
                      "%s." % output)

        error_context.context("Seek to one position and read file with "
                              "file-seek/read cmd.", logging.info)
        logging.info("Seek the position to file beginning and read all.")
        self.gagent.guest_file_seek(ret_handle, 0, 0)
        _read_check(ret_handle, "hello world")

        logging.info("Seek the position to file beginning and read 2 bytes.")
        self.gagent.guest_file_seek(ret_handle, 0, 0)
        _read_check(ret_handle, "he", 2)

        logging.info("Seek to current position, offset is 2 and read 5 byte.")
        self.gagent.guest_file_seek(ret_handle, 2, 1)
        _read_check(ret_handle, "o wor", 5)

        logging.info("Seek from the file end position, offset is -5 and "
                     "read 3 byte.")
        self.gagent.guest_file_seek(ret_handle, -5, 2)
        _read_check(ret_handle, "orl", 3)

        error_context.context("Close the opened file.", logging.info)
        self.gagent.guest_file_close(ret_handle)

    @error_context.context_aware
    def gagent_check_thaw_unfrozen(self, test, params, env):
        """
        Thaw the unfrozen fs

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        error_context.context("Verify if FS is thawed", logging.info)
        expect_status = self.gagent.FSFREEZE_STATUS_THAWED
        if self.gagent.get_fsfreeze_status() != expect_status:
            # Thaw guest FS if the fs status isn't thawed.
            self.gagent.fsthaw()
        error_context.context("Thaw the unfrozen FS", logging.info)
        ret = self.gagent.fsthaw(check_status=False)
        if ret != 0:
            test.fail("The return value of thawing an unfrozen fs is %s,"
                      "it should be zero" % ret)

    @error_context.context_aware
    def gagent_check_freeze_frozen(self, test, params, env):
        """
        Freeze the frozen fs

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        self.gagent.fsfreeze()
        error_context.context("Freeze the frozen FS", logging.info)
        try:
            self.gagent.fsfreeze(check_status=False)
        except guest_agent.VAgentCmdError as e:
            expected = ("The command guest-fsfreeze-freeze has been disabled "
                        "for this instance")
            if expected not in e.edata["desc"]:
                test.fail(e)
        else:
            test.fail("Cmd 'guest-fsfreeze-freeze' is executed successfully "
                      "after freezing FS! But it should return error.")
        finally:
            if self.gagent.get_fsfreeze_status() == self.gagent.FSFREEZE_STATUS_FROZEN:
                self.gagent.fsthaw(check_status=False)

    @error_context.context_aware
    def gagent_check_after_init(self, test, params, env):
        """
        Check guest agent service status after running the init command
        :param test: Kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment
        """
        error_context.context("Run init 3 in guest", logging.info)
        session = self._get_session(params, self.vm)
        session.cmd("init 3")
        error_context.context("Check guest agent status after running init 3",
                              logging.info)
        if self._check_ga_service(session, params.get("gagent_status_cmd")):
            logging.info("Guest agent service is still running after init 3.")
        else:
            test.fail("Guest agent service is stopped after running init 3! It "
                      "should be running.")

    @error_context.context_aware
    def gagent_check_hotplug_frozen(self, test, params, env):
        """
        hotplug device with frozen fs

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment
        """
        def get_new_disk(disks_before_plug, disks_after_plug):
            """
            Get the new added disks by comparing two disk lists.
            """
            disk = list(set(disks_after_plug).difference(set(disks_before_plug)))
            return disk

        session = self._get_session(params, self.vm)
        image_size_stg0 = params["image_size_stg0"]
        try:
            if params.get("os_type") == "linux":
                disks_before_plug = utils_disk.get_linux_disks(session, True)
            error_context.context("Freeze guest fs", logging.info)
            self.gagent.fsfreeze()
            # For linux guest, waiting for it to be frozen, for windows guest,
            # waiting for it to be automatically thawed.
            time.sleep(20)
            error_context.context("Hotplug a disk to guest", logging.info)
            image_name_plug = params["images"].split()[1]
            image_params_plug = params.object_params(image_name_plug)
            devs = self.vm.devices.images_define_by_params(image_name_plug,
                                                           image_params_plug,
                                                           'disk')
            for dev in devs:
                self.vm.devices.simple_hotplug(dev, self.vm.monitor)
            disk_write_cmd = params["disk_write_cmd"]
            pause = float(params.get("virtio_block_pause", 10.0))
            error_context.context("Format and write disk", logging.info)
            if params.get("os_type") == "linux":
                new_disks = utils_misc.wait_for(lambda: get_new_disk(disks_before_plug.keys(),
                                                utils_disk.get_linux_disks(session, True).keys()), pause)
                if not new_disks:
                    test.fail("Can't detect the new hotplugged disks in guest")
                try:
                    mnt_point = utils_disk.configure_empty_disk(
                        session, new_disks[0], image_size_stg0, "linux", labeltype="msdos")
                except aexpect.ShellTimeoutError:
                    self.gagent.fsthaw()
                    mnt_point = utils_disk.configure_empty_disk(
                        session, new_disks[0], image_size_stg0, "linux", labeltype="msdos")
            elif params.get("os_type") == "windows":
                disk_index = utils_misc.wait_for(
                    lambda: utils_disk.get_windows_disks_index(session, image_size_stg0), 120)
                if disk_index:
                    logging.info("Clear readonly for disk and online it in windows guest.")
                    if not utils_disk.update_windows_disk_attributes(session, disk_index):
                        test.error("Failed to update windows disk attributes.")
                    mnt_point = utils_disk.configure_empty_disk(
                        session, disk_index[0], image_size_stg0, "windows", labeltype="msdos")
            session.cmd(disk_write_cmd % mnt_point[0])
            error_context.context("Unplug the added disk", logging.info)
            self.vm.devices.simple_unplug(devs[0], self.vm.monitor)
        finally:
            if self.gagent.get_fsfreeze_status() == self.gagent.FSFREEZE_STATUS_FROZEN:
                self.gagent.fsthaw(check_status=False)
            self.vm.verify_alive()
            if params.get("os_type") == "linux":
                utils_disk.umount(new_disks[0], mnt_point[0], session=session)
            session.close()

    @error_context.context_aware
    def gagent_check_path_fsfreeze_hook(self, test, params, env):
        """
        Check if the default path of fsfreeze-hook is correct

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment
        """
        session = self._get_session(params, self.vm)
        self.gagent_stop(session, self.vm)
        error_context.context("Start gagent with -F option", logging.info)
        self.gagent_start(session, self.vm)
        gagent_path_cmd = params["gagent_path_cmd"]
        error_context.context("Check if default path of fsfreeze-hook is in "
                              "output of %s" % gagent_path_cmd, logging.info)
        s, o = session.cmd_status_output(params["gagent_help_cmd"])
        help_cmd_output = o.strip().replace(')', '').split()[-1]
        s, o = session.cmd_status_output(gagent_path_cmd)
        if help_cmd_output in o:
            logging.info("The default path for script 'fsfreeze-hook' is "
                         "in output of %s." % gagent_path_cmd)
            error_context.context("Execute 'guest-fsfreeze-freeze'", logging.info)
            self.gagent.fsfreeze()
            self.gagent.fsthaw()
        else:
            test.fail("The default path of fsfreeze-hook doesn't match with expectation.")

    @error_context.context_aware
    def gagent_check_query_chardev(self, test, params, env):
        """
        Check guest agent service status through QMP 'query-chardev'

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment
        """
        def check_value_frontend_open(out, expected):
            """
            Get value of 'frontend-open' after executing 'query-chardev'
            :param out: output of executing 'query-chardev'
            :param expected: expected value of 'frontend-open'
            """
            for chardev_dict in out:
                if "org.qemu.guest_agent.0" in chardev_dict["filename"]:
                    ret = chardev_dict["frontend-open"]
                    if ret is expected:
                        break
                    else:
                        test.fail("The value of parameter 'frontend-open' "
                                  "is %s, it should be %s" % (ret, expected))
        error_context.context("Execute query-chardev when guest agent service "
                              "is on", logging.info)
        out = self.vm.monitor.query("chardev")
        check_value_frontend_open(out, True)
        session = self._get_session(params, self.vm)
        self.gagent_stop(session, self.vm)
        error_context.context("Execute query-chardev when guest agent service "
                              "is off", logging.info)
        out = self.vm.monitor.query("chardev")
        check_value_frontend_open(out, False)
        session.close()

    def run_once(self, test, params, env):
        QemuGuestAgentTest.run_once(self, test, params, env)

        gagent_check_type = self.params["gagent_check_type"]
        chk_type = "gagent_check_%s" % gagent_check_type
        if hasattr(self, chk_type):
            func = getattr(self, chk_type)
            func(test, params, env)
        else:
            test.error("Could not find matching test, check your config file")


class QemuGuestAgentBasicCheckWin(QemuGuestAgentBasicCheck):

    """
    Qemu guest agent test class for windows guest.
    """
    def __init__(self, test, params, env):
        QemuGuestAgentBasicCheck.__init__(self, test, params, env)
        self.gagent_guest_dir = params["gagent_guest_dir"]
        self.qemu_ga_pkg = params["qemu_ga_pkg"]
        self.gagent_src_type = params.get("gagent_src_type", "url")

    @error_context.context_aware
    def get_qga_pkg_path(self, qemu_ga_pkg, test, session, params, vm):
        """
        Get the qemu-ga pkg path which will be installed.
        There are two methods to get qemu-ga pkg,one is download it
        from fedora people website,and the other is from virtio-win iso.

        :param qemu_ga_pkg: qemu-ga pkg name
        :param test: kvm test object
        :param session: VM session.
        :param params: Dictionary with the test parameters
        :param vm: Virtual machine object.
        :return qemu_ga_pkg_path: Return the guest agent pkg path.
        """
        error_context.context("Get %s path where it locates." % qemu_ga_pkg,
                              logging.info)

        if self.gagent_src_type == "url":
            gagent_host_path = params["gagent_host_path"]
            gagent_download_cmd = params["gagent_download_cmd"]

            error_context.context("Download qemu-ga.msi from website and copy "
                                  "it to guest.", logging.info)
            process.system(gagent_download_cmd, float(params.get("login_timeout", 360)))
            if not os.path.exists(gagent_host_path):
                test.error("qemu-ga.msi is not exist, maybe it is not "
                           "successfully downloaded ")
            s, o = session.cmd_status_output("mkdir %s" % self.gagent_guest_dir)
            if s and "already exists" not in o:
                test.error("Could not create qemu-ga directory in "
                           "VM '%s', detail: '%s'" % (vm.name, o))

            error_context.context("Copy qemu-ga.msi to guest", logging.info)
            vm.copy_files_to(gagent_host_path, self.gagent_guest_dir)
            qemu_ga_pkg_path = r"%s\%s" % (self.gagent_guest_dir, qemu_ga_pkg)
        elif self.gagent_src_type == "virtio-win":
            vol_virtio_key = "VolumeName like '%virtio-win%'"
            vol_virtio = utils_misc.get_win_disk_vol(session, vol_virtio_key)
            qemu_ga_pkg_path = r"%s:\%s\%s" % (vol_virtio, "guest-agent", qemu_ga_pkg)
        else:
            test.error("Only support 'url' and 'virtio-win' method to "
                       "download qga installer now.")

        logging.info("The qemu-ga pkg full path is %s" % qemu_ga_pkg_path)
        return qemu_ga_pkg_path

    @error_context.context_aware
    def setup(self, test, params, env):
        BaseVirtTest.setup(self, test, params, env)

        if self.start_vm == "yes":
            session = self._get_session(params, self.vm)
            qemu_ga_pkg_path = self.get_qga_pkg_path(self.qemu_ga_pkg, test,
                                                     session, params, self.vm)
            self.gagent_install_cmd = params.get("gagent_install_cmd"
                                                 ) % qemu_ga_pkg_path
            self.gagent_uninstall_cmd = params.get("gagent_uninstall_cmd"
                                                   ) % qemu_ga_pkg_path

            if self._check_ga_pkg(session, params.get("gagent_pkg_check_cmd")):
                logging.info("qemu-ga is already installed.")
            else:
                logging.info("qemu-ga is not installed.")
                self.gagent_install(session, self.vm)

            if self._check_ga_service(session, params.get("gagent_status_cmd")):
                logging.info("qemu-ga service is already running.")
            else:
                logging.info("qemu-ga service is not running.")
                self.gagent_start(session, self.vm)

            session.close()
            args = [params.get("gagent_serial_type"), params.get("gagent_name")]
            self.gagent_create(params, self.vm, *args)


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
