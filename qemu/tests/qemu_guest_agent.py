import logging
import time
import os
import re
import base64
import random
import string

import aexpect

from avocado.utils import genio
from avocado.utils import path as avo_path
from avocado.utils import process
from avocado.core import exceptions
from aexpect.exceptions import ShellTimeoutError

from virttest import error_context
from virttest import guest_agent
from virttest import utils_misc
from virttest import utils_disk
from virttest import env_process
from virttest import utils_net
from virttest import data_dir
from virttest import storage
from virttest import qemu_migration

from avocado import TestCancel


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
        Check if the package is installed, for rhel8 need to check
        if the current pkg is the latest one.

        :param session: use for sending cmd
        :param cmd_check_pkg: cmd to check if ga pkg is installed
        '''
        error_context.context("Check whether qemu-ga is installed.",
                              logging.info)
        s, o = session.cmd_status_output(cmd_check_pkg)
        if s == 0 and self.params.get("os_variant", "") == 'rhel8':
            # qemu-guest-agent-2.12.0-88.module+el8.1.0+4233+bc44be3f.x86_64
            error_context.context("Check if the installed pkg is the latest"
                                  " one for rhel8 guest.", logging.info)
            version_list = []
            build_latest = re.sub(r'/', '-', self.qga_pkg_latest_url)
            for pkg in [o, build_latest]:
                pattern = r"guest-agent-(\d+.\d+.\d+-\d+).module"
                qga_v = re.findall(pattern, pkg, re.I)[0]
                version_list.append(qga_v)
            logging.info("The installed and the latest pkg version is"
                         " %s" % version_list)
            if version_list[1] != version_list[0]:
                return False
        return s == 0

    @error_context.context_aware
    def _check_ga_service(self, session, cmd_check_status):
        '''
        Check if the service is started.
        :param session: use for sending cmd
        :param cmd_check_status: cmd to check if ga service is started
        '''
        error_context.context("Check whether qemu-ga service is started.",
                              logging.info)
        s, o = session.cmd_status_output(cmd_check_status)
        return s == 0

    def _get_main_qga_version(self, session, vm):
        """
        Get qemu-guest-agent version in guest
        :param session: use for sending cmd
        :param vm: guest object.
        :return: main qga version
        """
        logging.info("Get guest agent's main version for linux guest.")
        qga_ver = session.cmd_output(self.params["gagent_pkg_check_cmd"])
        pattern = r"guest-agent-(\d+).\d+.\d+-\d+"
        ver_main = int(re.findall(pattern, qga_ver)[0])
        return ver_main

    @error_context.context_aware
    def _get_latest_pkg(self):
        """
        get latest qemu-guest-agent rpm package url.
        :return: rpm pkg list
        """
        def get_mdl_tag_build_status(get_mdl_tag_cmd):
            """
            Get module tag and qemu-kvm build status.
            """
            logging.info("Get the needed module tag.")
            mdl_tag = process.system_output(get_mdl_tag_cmd,
                                            shell=True,
                                            timeout=query_timeout
                                            ).strip().split()[0].decode()
            logging.info("Check qemu-kvm build is ready or not")
            get_qemu_name_cmd = "brew list-tagged %s" % mdl_tag
            get_qemu_name_cmd += " | grep qemu-kvm"
            qemu_bild_name = process.system_output(get_qemu_name_cmd,
                                                   shell=True,
                                                   timeout=query_timeout
                                                   ).strip().split()[0].decode()
            get_build_ready_cmd = "brew buildinfo %s | grep State" % qemu_bild_name
            output = process.system_output(get_build_ready_cmd,
                                           shell=True,
                                           timeout=query_timeout
                                           ).strip().decode()
            return mdl_tag, "COMPLETE" in output

        virt_module_stream = self.params.get("virt_module_stream", "")
        guest_name = self.params.get("guest_name")
        arch = self.params["vm_arch_name"]
        download_root = self.params["download_root_url"]
        query_timeout = 180

        error_context.context("Check if brew command is presented.",
                              logging.info)
        try:
            avo_path.find_command("brew")
        except avo_path.CmdNotFoundError as detail:
            raise TestCancel(str(detail))

        error_context.context("Get the latest qemu-guest-agent pkg of %s"
                              " stream." % virt_module_stream,
                              logging.info)
        # target release,such as 810,811
        target_release = re.findall(r'rhel(\d+)-\w+', guest_name, re.I)[0]
        # get tag pattern,such as module-virt-8.1-80101xxxxx
        if virt_module_stream == "rhel":
            # for slow train,didn't know 810 or 811.
            # module-virt-rhel-801xxx
            target_release = target_release[:-1]
        tag_version = "0".join(target_release)
        # module-virt-8.1-80101 or module-virt-rhel-801
        platform_tag = "module-virt-%s-%s" % (virt_module_stream,
                                              tag_version)
        get_latest_mdl_tag_cmd = "brew list-targets |grep"
        get_latest_mdl_tag_cmd += " %s |sort -r |head -n 1" % platform_tag
        mdl_tag, build_s = get_mdl_tag_build_status(get_latest_mdl_tag_cmd)

        if not build_s:
            logging.info("The qemu-kvm build's status is not ready,"
                         " so we well check it in the previous virt module")
            get_pre_mdl_tag_cmd = "brew list-targets |grep %s" % platform_tag
            get_pre_mdl_tag_cmd += " |sort -r |head -n 2 |tail -n 1"
            mdl_tag, build_s = get_mdl_tag_build_status(
                get_pre_mdl_tag_cmd)
            if not build_s:
                self.test.error("Please check why the recent two modules'"
                                " qemu-kvm build is not ready.")

        error_context.context("Get qemu-guest-agent rpm pkg"
                              " url of %s." % mdl_tag, logging.info)
        get_brew_latest_pkg_cmd = "brew --quiet --topdir=%s" % download_root
        get_brew_latest_pkg_cmd += " list-tagged %s" % mdl_tag
        get_brew_latest_pkg_cmd += " --path --arch=%s" % arch
        get_brew_latest_pkg_cmd += " |grep qemu-guest-agent-[0-9]"

        rpm_url = process.system_output(get_brew_latest_pkg_cmd,
                                        shell=True,
                                        timeout=query_timeout
                                        ).strip().decode()
        logging.info("Qemu-guest-agent rpm pkg url is %s" % rpm_url)
        return rpm_url

    def gagent_install(self, session, vm):
        """
        install qemu-ga pkg in guest.
        :param session: use for sending cmd
        :param vm: guest object.
        """
        error_context.context("Try to install 'qemu-guest-agent' package.",
                              logging.info)
        if self.params.get("os_variant", "") == 'rhel8':
            cmd = self.params["gagent_pkg_check_cmd"]
            s_check, o_check = session.cmd_status_output(cmd)
            if s_check == 0:
                error_context.context("Remove the original guest agent pkg.",
                                      logging.info)
                session.cmd("rpm -e %s" % o_check.strip())
            self.gagent_install_cmd = "rpm -ivh %s" % self.qga_pkg_latest_url

        error_context.context("Install qemu-guest-agent pkg in guest.",
                              logging.info)
        s_inst, o_inst = session.cmd_status_output(self.gagent_install_cmd)
        if s_inst != 0:
            self.test.fail("qemu-guest-agent install failed,"
                           " the detailed info:\n%s." % o_inst)
        if self.params.get("os_variant", "") == 'rhel8' and s_check == 0:
            error_context.context("A new pkg is installed, so restart"
                                  " qemu-guest-agent service.",
                                  logging.info)
            restart_cmd = self.params["gagent_restart_cmd"]
            s_rst, o_rst = session.cmd_status_output(restart_cmd)
            if s_rst != 0:
                self.test.fail("qemu-guest-agent service restart failed,"
                               " the detailed info:\n%s." % o_rst)

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

        filename = vm.get_serial_console_filename(gagent_name)
        gagent_params = params.object_params(gagent_name)
        gagent_params["monitor_filename"] = filename
        gagent = guest_agent.QemuAgent(vm, gagent_name, gagent_serial_type,
                                       gagent_params, get_supported_cmds=True)
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
    def gagent_setsebool_value(self, value, params, vm):
        '''
        Set selinux boolean 'virt_qemu_ga_read_nonsecurity_files'
        as 'on' or 'off' for linux guest can access filesystem
        successfully and restore guest original env when test is over.

        :param value: value of selinux boolean.
        :param params: Dictionary with the test parameters
        :param vm: Virtual machine object.
        '''
        session = self._get_session(params, vm)
        self._open_session_list.append(session)
        error_context.context("Turn %s virt_qemu_ga_read_nonsecurity_files." %
                              value, logging.info)
        set_selinux_bool_cmd = params["setsebool_cmd"] % value
        session.cmd(set_selinux_bool_cmd).strip()
        get_sebool_cmd = params['getsebool_cmd']
        value_selinux_bool_guest = session.cmd_output(get_sebool_cmd).strip()
        if value_selinux_bool_guest != value:
            self.test.error("Set boolean virt_qemu_ga_read_nonsecurity_files "
                            "failed.")

    @error_context.context_aware
    def log_persistence(self, params, session):
        """
        Create new log directory and make it as log persistence.
        """
        error_context.context("Make logs persistent.", logging.info)
        session.cmd(params["cmd_prepared_and_restart_journald"])

    @error_context.context_aware
    def setup(self, test, params, env):
        BaseVirtTest.setup(self, test, params, env)
        if self.start_vm == "yes":
            session = self._get_session(params, self.vm)
            self._open_session_list.append(session)
            if self.params.get("os_variant", "") == 'rhel8':
                error_context.context("Get the latest qemu-guest-agent pkg"
                                      " for rhel8 guest.", logging.info)
                self.qga_pkg_latest_url = self._get_latest_pkg()
            if self._check_ga_pkg(session, params.get("gagent_pkg_check_cmd")):
                logging.info("qemu-ga is already installed.")
            else:
                logging.info("qemu-ga is not installed or need to update.")
                self.gagent_install(session, self.vm)

            if self._check_ga_service(session, params.get("gagent_status_cmd")):
                logging.info("qemu-ga service is already running.")
            else:
                logging.info("qemu-ga service is not running.")
                self.gagent_start(session, self.vm)

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

    @error_context.context_aware
    def gagent_check_powerdown(self, test, params, env):
        """
        Shutdown guest with guest agent command "guest-shutdown"

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environmen.
        """
        def _gagent_check_shutdown(self):
            self.__gagent_check_shutdown(self.gagent.SHUTDOWN_MODE_POWERDOWN)
            if not utils_misc.wait_for(self.vm.is_dead, self.vm.REBOOT_TIMEOUT):
                test.fail("Could not shutdown VM via guest agent'")

        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)

        if params.get("os_type") == "linux":
            self.log_persistence(params, session)
            _gagent_check_shutdown(self)

            time.sleep(20)
            env_process.preprocess_vm(test, params, env, params["main_vm"])
            self.vm = env.get_vm(params["main_vm"])
            session = self.vm.wait_for_login(timeout=int(params.get("login_timeout",
                                             360)))

            error_context.context("Check if guest-agent crash after reboot.",
                                  logging.info)
            output = session.cmd_output(params["cmd_query_log"], timeout=10)
            try:
                if "core-dump" in output:
                    test.fail("Guest-agent aborts after guest-shutdown"
                              " detail: '%s'" % output)
            finally:
                session.cmd('rm -rf %s' % params['journal_file'])
        else:
            _gagent_check_shutdown(self)

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
        Execute "guest-get-vcpus" command to guest agent.

        Steps:
        1) Check can-offline field of guest agent.
        2) Check cpu number.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)

        error_context.context("Check can-offline field of guest agent.",
                              logging.info)
        vcpus_info = self.gagent.get_vcpus()
        cpu_num_qga = len(vcpus_info)
        for vcpu in vcpus_info:
            if params.get("os_type") == "linux":
                if vcpu["logical-id"] == 0:
                    vcpu_can_offline_qga = vcpu["can-offline"]
                    cmd = "find /sys/devices/system/cpu/cpu0/ -name online"
                    if session.cmd_output(cmd):
                        vcpu_can_offline_guest = True
                    else:
                        vcpu_can_offline_guest = False
                    if vcpu_can_offline_qga != vcpu_can_offline_guest:
                        test.fail("The first logical vcpu's can-offline field"
                                  " isn't aligned with what it's in guest.")
                if vcpu["logical-id"] != 0 and vcpu["can-offline"] is False:
                    test.fail("The vcpus should be able to offline "
                              "except vcpu0.")
            if params.get("os_type") == "windows" and vcpu["can-offline"]:
                test.fail("All vcpus should not be able to offline in"
                          " windows guest.")

        error_context.context("Check cpu number.", logging.info)
        output = session.cmd_output(params["get_cpu_cmd"])

        if params.get("os_type") == "windows":
            cpu_list = output.strip().split('\n')
            cpu_num_guest = sum(map(int, cpu_list))
        else:
            cpu_num_guest = int(output)

        if cpu_num_qga != cpu_num_guest:
            test.fail("CPU number doen't match.\n"
                      "number from guest os is %s,number from guest-agent is %s." %
                      (cpu_num_guest, cpu_num_qga))

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
    def gagent_check_set_mem_blocks(self, test, params, env):
        """
        Get/set logical memory blocks via guest agent.
        Steps:
        1) Get the size of memory block unit via guest agent
        2) Offline one memory block which can be removable in guest
        3) Verify memory blocks via guest agent is offline
        4) Verify memory block unit size
        5) Offline some memory blocks which can be offline via guest agent
        6) Verify memory are decreased in guest
        7) Online the memory blocks which are offline before
        8) Verify memory are the same as before
        9) Offline a memroy block which can't be offline

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        session = self._get_session(params, None)
        self._open_session_list.append(session)
        cmd_get_mem = "free -m |grep -i mem"
        cmd_offline_mem = "echo 0 > /sys/devices/system/memory/memory%s/online"
        # record the memory blocks phys-index which is set to offline
        mem_off_phys_index_list = []

        error_context.context("Get the size of memory block unit.",
                              logging.info)
        mem_block_info = self.gagent.get_memory_block_info()["size"]
        mem_unit_size = mem_block_info / float(1024 * 1024)

        error_context.context("Offline one memory block in guest.",
                              logging.info)
        mem_size_original = session.cmd_output(cmd_get_mem).strip().split()[1]
        mem_blocks = self.gagent.get_memory_blocks()
        mem_list_index = 0
        for memory in mem_blocks:
            if memory["online"] and memory["can-offline"]:
                mem_phys_index = memory["phys-index"]
                mem_off_phys_index_list.append(mem_phys_index)
                break
            mem_list_index += 1
        else:
            logging.info("All memory blocks are offline already.")
            return
        session.cmd(cmd_offline_mem % mem_phys_index)

        error_context.context("Verify it's changed to offline status via"
                              " agent.", logging.info)
        mem_blocks = self.gagent.get_memory_blocks()
        if mem_blocks[mem_list_index]["online"] is not False:
            test.fail("%s phys-index memory block is still online"
                      " via agent." % mem_phys_index)

        error_context.context("Verify the memory block unit size.",
                              logging.info)
        mem_size = session.cmd_output(cmd_get_mem)
        mem_size_aft_offline_guest = mem_size.strip().split()[1]
        delta = float(mem_size_original) - float(mem_size_aft_offline_guest)
        if delta != mem_unit_size:
            test.fail("Memory block info is not correct\nit's %s via agent\n"
                      "it's %s via guest." % (mem_unit_size, delta))

        error_context.context("Offline some memory blocks which can be"
                              " offline via agent.", logging.info)
        # record the memory blocks which will be offline
        mem_blocks_list = []
        count = 0
        # offline 5 or less memory blocks
        for memory in mem_blocks:
            if memory["online"] and memory["can-offline"]:
                mem_phys_index = memory["phys-index"]
                mem_off_phys_index_list.append(mem_phys_index)
                mem_obj = {"online": False, "can-offline": True,
                           "phys-index": mem_phys_index}
                mem_blocks_list.append(mem_obj)
                count += 1
                if count >= 5:
                    break
        if mem_blocks_list is not None:
            self.gagent.set_memory_blocks(mem_blocks_list)
            error_context.context("Verify memory size is decreased after"
                                  " offline.", logging.info)
            mem_size = session.cmd_output(cmd_get_mem)
            mem_size_aft_offline_qga = mem_size.strip().split()[1]
            if float(mem_size_aft_offline_qga) >= \
                    float(mem_size_aft_offline_guest):
                test.fail("Memory isn't decreased\nsize before is %s\n"
                          "size after is %s" % (mem_size_aft_offline_guest,
                                                mem_size_aft_offline_qga))
        else:
            logging.info("The memory blocks are already offline,"
                         " no need to do offline operation.")

        error_context.context("Recovery the memory blocks which are set to"
                              " offline before.", logging.info)
        # record the memory blocks which will be online
        mem_blocks_list = []
        for mem_phys_index in mem_off_phys_index_list:
            mem_obj = {"online": True, "can-offline": True,
                       "phys-index": mem_phys_index}
            mem_blocks_list.append(mem_obj)
        self.gagent.set_memory_blocks(mem_blocks_list)
        mem_size_final = session.cmd_output(cmd_get_mem).strip().split()[1]
        if float(mem_size_final) != float(mem_size_original):
            test.fail("Memory is not the same with original\n"
                      "original size is %s\nfinal size is %s." %
                      (mem_size_original, mem_size_final))

        error_context.context("Offline one memory block which can't be"
                              " offline.", logging.info)
        mem_blocks = self.gagent.get_memory_blocks()
        for memory in mem_blocks:
            if memory["online"] and memory["can-offline"] is False:
                mem_obj_index = memory["phys-index"]
                break
        else:
            logging.info("There is no required memory block that can-offline"
                         " attribute is False.")
            return
        mem_blocks_list = [{"online": False, "can-offline": True,
                            "phys-index": mem_obj_index}]
        result = self.gagent.set_memory_blocks(mem_blocks_list)
        if "operation-failed" not in result[0]["response"]:
            test.fail("Didn't return the suitable description,"
                      " the output info is %s." % result)

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
        steps:
        1) Query the timestamp of current time in guest
        2) Move the guest time one week into the past with command "guest-set-time"
        3) Check if the guest time is set
        4) Set a invalid guest time if needed
        5) Set the system time from the hwclock for rhel guest

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
        error_context.context("the time before being moved back into past is '%d' "
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

        # set invalid guest time if needed
        invalid_time_test = params.get_boolean("invalid_time_test")
        if invalid_time_test:
            error_context.context("Set time to an invalid value.",
                                  logging.info)
            guest_time_before_invalid = session.cmd_output(get_guest_time_cmd)
            target_time_invalid = int(guest_time_before) * 1000000000000
            try:
                self.gagent.set_time(target_time_invalid)
            except guest_agent.VAgentCmdError as e:
                expected = "Invalid parameter type"
                if expected not in e.edata["desc"]:
                    test.fail(str(e))
            guest_time_after_invalid = session.cmd_output(get_guest_time_cmd)
            delta = abs(int(guest_time_after_invalid) - int(
                guest_time_before_invalid))
            # time should have no change after invalid time set, 1min is
            # acceptable as there are some check during test
            if delta > 60:
                test.fail("The guest time is changed after invalid time set.")
            return
        # Only for linux guest, set the system time from the hwclock
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
    def gagent_check_time_sync(self, test, params, env):
        """
        Run "guest-set-time" to sync time after stop/cont vm

        Steps:
        1) start windows time service in guest and
        change ntp server to clock.redhat.com
        2) stop vm
        3) wait 3 mins and resume vm
        4) execute "guest-set-time" cmd via qga
        5) query time offset of vm,it should be less than 3 seconds

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        def time_drift():
            """
            Get the time diff between host and guest
            :return: time diff
            """
            host_time = process.system_output("date +%s")
            get_guest_time_cmd = params["get_guest_time_cmd"]
            guest_time = session.cmd_output(get_guest_time_cmd)
            logging.info("Host time is %s,guest time is %s." % (host_time,
                                                                guest_time))
            time_diff = abs(int(host_time) - int(guest_time))
            return time_diff

        time_config_cmd = params["time_service_config"]
        time_service_status_cmd = params["time_service_status_cmd"]
        time_service_start_cmd = params["time_service_start_cmd"]
        time_service_stop_cmd = params["time_service_stop_cmd"]
        session = self._get_session(self.params, self.vm)
        self._open_session_list.append(session)

        error_context.context("Start windows time service.", logging.info)
        if session.cmd_status(time_service_status_cmd):
            session.cmd(time_service_start_cmd)

        error_context.context("Config time resource and restart time"
                              " service.", logging.info)
        session.cmd(time_config_cmd)
        session.cmd(time_service_stop_cmd)
        session.cmd(time_service_start_cmd)

        error_context.context("Stop the VM", logging.info)
        self.vm.pause()
        self.vm.verify_status("paused")

        pause_time = float(params["pause_time"])
        error_context.context("Sleep %s seconds." % pause_time, logging.info)
        time.sleep(pause_time)

        error_context.context("Resume the VM", logging.info)
        self.vm.resume()
        self.vm.verify_status("running")

        time_diff_before = time_drift()
        if time_diff_before < (pause_time - 5):
            test.error("Time is not paused about %s seconds." % pause_time)

        error_context.context("Execute guest-set-time cmd.", logging.info)
        self.gagent.set_time()

        logging.info("Wait a few seconds up to 30s to check guest time.")
        endtime = time.time() + 30
        while time.time() < endtime:
            time.sleep(2)
            time_diff_after = time_drift()
            if time_diff_after < 3:
                break
        else:
            test.fail("The guest time sync failed.")

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
        self.gagent_setsebool_value('on', params, self.vm)

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
        self.gagent_setsebool_value('off', params, self.vm)

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

        Steps:
        1) login guest with serial session
        2) get the available interface name via mac address
        3) check the available interface name is the same with guest
        4) check ip address is the same with guest
        5) create a bridge interface for linux guest and check it
           from guest agent;
           disable interface for windows guest and check it
           from guest agent
        6) check "guest-network-get-interfaces" result
        7) recover the interfaces
        8) change ip address
        9) check "guest-network-get-interfaces" result

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        def get_interface(ret_list, mac_addr):
            """
            Get the available interface name.

            :return: interface name and the interface's index in ret_list
            """
            interface_name = ""
            if_index = 0
            for interface in ret_list:
                if "hardware-address" in interface and \
                                interface["hardware-address"] == mac_addr:
                    interface_name = interface["name"]
                    break
                if_index += 1
            return interface_name, if_index

        def ip_addr_check(session, mac_addr, ret_list, if_index, if_name):
            """
            Check the ip address from qga and guest inside.

            :param session: serial session
            :param mac_addr: mac address of nic
            :param ret_list: return list from qg
            :param if_index: the interface's index in ret
            :param if_name: interface name
            """
            guest_ip_ipv4 = utils_net.get_guest_ip_addr(session, mac_addr,
                                                        os_type)
            guest_ip_ipv6 = utils_net.get_guest_ip_addr(session, mac_addr,
                                                        os_type,
                                                        ip_version="ipv6",
                                                        linklocal=True)
            ip_lists = ret_list[if_index]["ip-addresses"]
            for ip in ip_lists:
                if ip["ip-address-type"] == "ipv4":
                    ip_addr_qga_ipv4 = ip["ip-address"]
                elif ip["ip-address-type"] == "ipv6":
                    ip_addr_qga_ipv6 = ip["ip-address"].split("%")[0]
                else:
                    test.fail("The ip address type is %s, but it should be"
                              " ipv4 or ipv6." % ip["ip-address-type"])
            if guest_ip_ipv4 != ip_addr_qga_ipv4 \
                    or guest_ip_ipv6 != ip_addr_qga_ipv6:
                test.fail("Get the wrong ip address for %s interface:\n"
                          "ipv4 address from qga is %s, the expected is %s;\n"
                          "ipv6 address from qga is %s, the expected is %s."
                          % (if_name, ip_addr_qga_ipv4,
                             guest_ip_ipv4, ip_addr_qga_ipv6,
                             guest_ip_ipv6))

        session_serial = self.vm.wait_for_serial_login()
        mac_addr = self.vm.get_mac_address()
        os_type = self.params["os_type"]

        error_context.context("Get the available interface name via"
                              " guest-network-get-interfaces cmd.",
                              logging.info)
        ret = self.gagent.get_network_interface()
        if_name, if_index = get_interface(ret, mac_addr)
        if not if_name:
            test.fail("Did not get the expected interface,"
                      " the network info is \n%s." % ret)

        error_context.context("Check the available interface name %s"
                              " via qga." % if_name, logging.info)
        if os_type == "linux":
            if_name_guest = utils_net.get_linux_ifname(session_serial,
                                                       mac_addr)
        else:
            if_name_guest = utils_net.get_windows_nic_attribute(
                session_serial, "macaddress", mac_addr, "netconnectionid")
        if if_name != if_name_guest:
            test.fail("Get the wrong interface name, value from qga is: %s; "
                      "the expected is: %s" % (if_name, if_name_guest))

        error_context.context("Check ip address via qga.", logging.info)
        ip_addr_check(session_serial, mac_addr, ret, if_index, if_name)

        # create a bridge interface for linux guest and check it
        #  from guest agent
        # disable interface for windows guest and check it
        #  from guest agent
        if os_type == "linux":
            error_context.context("Create a new bridge in guest and check the"
                                  "result from qga.", logging.info)
            add_brige_cmd = "ip link add name br0 type bridge"
            session_serial.cmd(add_brige_cmd)
            interfaces_after_add = self.gagent.get_network_interface()
            for interface in interfaces_after_add:
                if interface["name"] == "br0":
                    break
            else:
                test.fail("The new bridge is not checked from guest agent.")
            error_context.context("Delete the added bridge.", logging.info)
            del_brige_cmd = "ip link del br0"
            session_serial.cmd(del_brige_cmd)
        else:
            error_context.context("Set down the interface in windows guest.",
                                  logging.info)
            utils_net.disable_windows_guest_network(session_serial, if_name)
            ret_after_down = self.gagent.get_network_interface()
            if_name_down = get_interface(ret_after_down, mac_addr)[0]
            if if_name_down:
                test.fail("From qga result that the interface is still"
                          " enabled, detailed info is:\n %s"
                          % ret_after_down)
            error_context.context("Set up the interface in guest.",
                                  logging.info)
            utils_net.enable_windows_guest_network(session_serial, if_name)

        error_context.context("Change ipv4 address and check the result "
                              "from qga.", logging.info)
        # for linux guest, need to delete ip address first
        if os_type == "linux":
            ip_lists = ret[if_index]["ip-addresses"]
            for ip in ip_lists:
                if ip["ip-address-type"] == "ipv4":
                    ip_addr_qga_ipv4 = ip["ip-address"]
                    break
            session_serial.cmd("ip addr del %s dev %s" % (ip_addr_qga_ipv4,
                                                          if_name))
        utils_net.set_guest_ip_addr(session_serial, mac_addr, "192.168.10.10",
                                    os_type=os_type)
        ret_ip_change = self.gagent.get_network_interface()
        if_name_ip_change, if_index_ip_change = get_interface(
            ret_ip_change, mac_addr)
        ip_addr_check(session_serial, mac_addr, ret_ip_change,
                      if_index_ip_change, if_name_ip_change)

        if session_serial:
            session_serial.close()

    @error_context.context_aware
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

    def _change_bl(self, session):
        """
        Some cmds are in blacklist by default,so need to change.
        Now only linux guest has this behavior,but still leave interface
        for windows guest.
        """
        if self.params.get("os_type") == "linux":
            cmd_black_list = self.params["black_list"]
            cmd_blacklist_backup = self.params["black_list_backup"]
            session.cmd(cmd_blacklist_backup)
            for black_cmd in cmd_black_list.split():
                bl_check_cmd = self.params["black_list_check_cmd"] % black_cmd
                bl_change_cmd = self.params["black_list_change_cmd"] % black_cmd
                session.cmd(bl_change_cmd)
                output = session.cmd_output(bl_check_cmd)
                if not output == "":
                    self.test.fail("Failed to change the cmd to "
                                   "white list, the output is %s" % output)

            s, o = session.cmd_status_output(self.params["gagent_restart_cmd"])
            if s:
                self.test.fail("Could not restart qemu-ga in VM after changing"
                               " list, detail: %s" % o)

    def _change_bl_back(self, session):
        """
        Change the blacklist_bck back for recovering guest env.
        """
        if self.params.get("os_type") == "linux":
            cmd_change_bl_back = self.params["recovery_black_list"]
            session.cmd(cmd_change_bl_back)

    def _read_check(self, ret_handle, content, count=None):
        """
        Read file and check if the content read is correct.

        :param ret_handle: file handle returned by guest-file-open
        :param count: maximum number of bytes to read
        :param content: expected content
        """
        logging.info("Read content and do check.")
        ret_read = self.gagent.guest_file_read(ret_handle, count=count)
        content_read = base64.b64decode(ret_read["buf-b64"]).decode()
        logging.info("The read content is '%s'; the real content is '%s'."
                     % (content_read, content))
        if not content_read.strip() == content.strip():
            self.test.fail("The read content is '%s'; the real content is '%s'."
                           % (content_read, content))

    def _guest_file_prepare(self):
        """
        Preparation for gagent_check_file_xxx function.
        :return: vm session and guest file full path
        """
        session = self._get_session(self.params, self.vm)
        self._open_session_list.append(session)
        logging.info("Change guest-file related cmd to white list.")
        self._change_bl(session)

        ranstr = utils_misc.generate_random_string(5)
        file_name = "qgatest" + ranstr
        guest_file = "%s%s" % (self.params["file_path"], file_name)
        return session, guest_file

    @error_context.context_aware
    def gagent_check_file_seek(self, test, params, env):
        """
        Guest-file-seek cmd test.

        Test steps:
        1) create new guest file in guest.
        2) write "hello world" to guest file.
        3) seek test
          a.seek from the file beginning position and offset is 0
           ,and read two count
          b. seek from the file beginning position and offset is 0,
           read two bytes.
          c. seek from current position and offset is 2,read 5 bytes.
          d. seek from the file end and offset is -5,read 3 bytes.
        4) close the handle

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        error_context.context("Change guest-file related cmd to white list"
                              " and get guest file name.")
        session, tmp_file = self._guest_file_prepare()

        error_context.context("Write content to file.", logging.info)
        content = "hello world\n"
        ret_handle = int(self.gagent.guest_file_open(tmp_file, mode="w+"))
        self.gagent.guest_file_write(ret_handle, content)
        self.gagent.guest_file_flush(ret_handle)

        error_context.context("Seek to one position and read file with "
                              "file-seek/read cmd.", logging.info)
        self.gagent.guest_file_seek(ret_handle, 0, 0)
        self._read_check(ret_handle, content)

        logging.info("Seek the position to file beginning and read all.")
        self.gagent.guest_file_seek(ret_handle, 0, 0)
        self._read_check(ret_handle, "he", 2)

        logging.info("Seek the position to file beginning, offset is 2, and read 2 bytes.")
        self.gagent.guest_file_seek(ret_handle, 2, 0)
        self._read_check(ret_handle, "ll", 2)

        logging.info("Seek to current position, offset is 2 and read 5 byte.")
        self.gagent.guest_file_seek(ret_handle, 2, 1)
        self._read_check(ret_handle, "world", 5)

        logging.info("Seek from the file end position, offset is -5 and "
                     "read 3 byte.")
        self.gagent.guest_file_seek(ret_handle, -5, 2)
        self._read_check(ret_handle, "orl", 3)

        self.gagent.guest_file_close(ret_handle)
        cmd_del_file = "%s %s" % (params["cmd_del"], tmp_file)
        session.cmd(cmd_del_file)
        self._change_bl_back(session)

    @error_context.context_aware
    def gagent_check_file_write(self, test, params, env):
        """
        Guest-file-write cmd test.

        Test steps:
        1) write two counts bytes to guest file.
        2) write ten counts bytes to guest file from the file end.
        3) write more than all counts bytes to guest file.
        4) close the handle

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        error_context.context("Change guest-file related cmd to white list"
                              " and get guest file name.")
        session, tmp_file = self._guest_file_prepare()

        error_context.context("Create new file with mode 'w' and do file"
                              " write test", logging.info)
        ret_handle = int(self.gagent.guest_file_open(tmp_file, mode="w+"))
        content = "hello world\n"
        content_check = ""
        for cnt in range(1, 10, 2):
            error_context.context("Write %s bytes to guest file."
                                  % cnt, logging.info)
            self.gagent.guest_file_seek(ret_handle, 0, 2)
            self.gagent.guest_file_write(ret_handle, content, cnt)
            self.gagent.guest_file_flush(ret_handle)
            self.gagent.guest_file_seek(ret_handle, 0, 0)
            content_check += content[: int(cnt)]
            self._read_check(ret_handle, content_check)

        error_context.context("Write more than all counts bytes to"
                              " guest file.", logging.info)
        try:
            self.gagent.guest_file_write(ret_handle, content, 15)
        except guest_agent.VAgentCmdError as e:
            expected = "invalid for argument count"
            if expected not in e.edata["desc"]:
                self.test.fail(e)
        else:
            self.test.fail("Cmd 'guest-file-write' is executed "
                           "successfully after freezing FS! "
                           "But it should return error.")
        self.gagent.guest_file_close(ret_handle)
        cmd_del_file = "%s %s" % (params["cmd_del"], tmp_file)
        session.cmd(cmd_del_file)
        self._change_bl_back(session)

    @error_context.context_aware
    def gagent_check_file_read(self, test, params, env):
        """
        Guest-file-read cmd test.

        Test steps:
        1) create a file in guest.
        2) read the file via qga command and check the result.
        3) create a big file in guest.
        4) Read the big file with an invalid count number.
        5) Read the big file with big count number.
        6) Open a none existing file of guest.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        def _read_guest_file_with_count(count_num):
            """
            Read a guest file with count number.

            :params: count_num: read file with count number on demand.
            """
            try:
                self.gagent.guest_file_read(ret_handle, count=int(count_num))
            except guest_agent.VAgentCmdError as detail:
                info_insuffi = "Insufficient system resources exist to"
                info_insuffi += " complete the requested service"
                if info_insuffi not in detail.edata['desc']:
                    test.fail("Return error but is not the desired information: "
                              "('%s')" % str(detail))

        error_context.context("Change guest-file related cmd to white list"
                              " and get guest file name.")
        session, tmp_file = self._guest_file_prepare()
        content = "helloworld\n"

        error_context.context("Create a new small file in guest", logging.info)
        cmd_create_file = "echo helloworld > %s" % tmp_file
        session.cmd(cmd_create_file)
        error_context.context("Open guest file via guest-file-open with"
                              " read only mode.", logging.info)
        # default is read mode
        ret_handle = int(self.gagent.guest_file_open(tmp_file))
        error_context.context("Read the content and check the result via"
                              " guest-file cmd", logging.info)
        self._read_check(ret_handle, content)
        self.gagent.guest_file_close(ret_handle)

        error_context.context("Create a 200KB file in guest", logging.info)
        process.run("dd if=/dev/urandom of=/tmp/big_file bs=1024 count=200")
        self.vm.copy_files_to("/tmp/big_file", tmp_file)

        error_context.context("Open the big guest file via guest-file-open with"
                              " read only mode.", logging.info)
        ret_handle = int(self.gagent.guest_file_open(tmp_file))

        error_context.context("Read the big file with an invalid count number",
                              logging.info)
        if params.get("os_type") == "linux":
            main_qga_ver = self._get_main_qga_version(session, self.vm)
        if params.get("os_type") == "linux" and main_qga_ver <= 2:
            # if resource is sufficient can read file,
            # else file handle will not be found.
            self.gagent.guest_file_read(ret_handle, count=10000000000)
            try:
                self.gagent.guest_file_seek(ret_handle, 0, 0)
            except guest_agent.VAgentCmdError as detail:
                if re.search("handle '%s' has not been found" % ret_handle,
                             str(detail)):
                    msg = "As resouce is not sufficient, "
                    msg += "file is closed, so open the file again to "
                    msg += "continue the following tests."
                    logging.info(msg)
                    ret_handle = int(self.gagent.guest_file_open(tmp_file))
        else:
            # for windows os or qga version > 2 for linux os,
            # the large count number is an invalid parameter from qga.
            try:
                self.gagent.guest_file_read(ret_handle, count=10000000000)
            except guest_agent.VAgentCmdError as detail:
                if not re.search("invalid for argument count", str(detail)):
                    test.fail("Return error but is not the desired info: "
                              "('%s')" % str(detail))
                else:
                    logging.info("The count number is invalid for windows"
                                 " guest and linux guest in which qga version"
                                 " is bigger than 2.")
            else:
                test.fail("Did not get the expected result.")

        error_context.context("Read the file with an valid big count"
                              " number.", logging.info)
        self.gagent.guest_file_seek(ret_handle, 0, 0)
        # if guest os resource is enough, will return no error.
        # else it will return error like "insufficient system resource"
        # which is expected
        count = 1000000000 if (params["os_type"] == 'linux' and
                               main_qga_ver < 5) else 10000000
        _read_guest_file_with_count(count)
        self.gagent.guest_file_close(ret_handle)

        error_context.context("Open a none existing file with read only mode.",
                              logging.info)
        try:
            self.gagent.guest_file_open("none_exist_file")
        except guest_agent.VAgentCmdError as detail:
            res_linux = "No such file or directory"
            res_windows = "system cannot find the file"
            if res_windows not in str(detail) and res_linux not in str(detail):
                test.fail("This is not the desired information: "
                          "('%s')" % str(detail))
        else:
            test.fail("Should not pass with none existing file.")

        cmd_del_file = "%s %s" % (params["cmd_del"], tmp_file)
        session.cmd(cmd_del_file)
        self._change_bl_back(session)

    @error_context.context_aware
    def gagent_check_with_fsfreeze(self, test, params, env):
        """
        Try to operate guest file when fs freeze.

        Test steps:
        1) freeze fs and try to open guest file with qga cmd.
        2) after thaw fs, try to operate guest file with qga cmd.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        error_context.context("Change guest-file related cmd to white list"
                              " and get guest file name.")
        session, tmp_file = self._guest_file_prepare()

        content = "hello world\n"
        error_context.context("Freeze fs and try to open guest file.",
                              logging.info)
        self.gagent.fsfreeze()
        try:
            self.gagent.guest_file_open(tmp_file, mode="a+")
        except guest_agent.VAgentCmdError as detail:
            if not re.search('guest-file-open has been disabled',
                             str(detail)):
                self.test.fail("This is not the desired information: "
                               "('%s')" % str(detail))
        else:
            self.test.fail("guest-file-open command shouldn't succeed "
                           "for freeze FS.")
        finally:
            self.gagent.fsthaw()

        error_context.context("After thaw fs, try to operate guest"
                              " file.", logging.info)
        ret_handle = int(self.gagent.guest_file_open(tmp_file, mode="a+"))
        self.gagent.guest_file_write(ret_handle, content)
        self.gagent.guest_file_flush(ret_handle)
        self.gagent.guest_file_seek(ret_handle, 0, 0)
        self._read_check(ret_handle, "hello world")
        self.gagent.guest_file_close(ret_handle)
        cmd_del_file = "%s %s" % (params["cmd_del"], tmp_file)
        session.cmd(cmd_del_file)
        self._change_bl_back(session)

    @error_context.context_aware
    def gagent_check_with_selinux(self, test, params, env):
        """
        File operation via guest agent when selinux policy is in "Enforcing"
         mode and "Permissive" mode.

        Steps:
        1) set selinux policy to "Enforcing" mode in guest
        2) create and write content to temp file and non temp file
        3) open the temp file with w+ mode and a+ mode
        4) open the non temp file with w+ mode and a+ mode
        5) set selinux policy to "Permissive" in guest
        6) repeate step3-4
        7) recovery the selinux policy
        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        def file_operation(guest_file, open_mode):
            """
            open/write/flush/close file test.

            :param guest_file: file in guest
            :param open_mode: open file mode, "r" is the default value
            """
            ret_handle = self.gagent.guest_file_open(guest_file,
                                                     mode=open_mode)
            self.gagent.guest_file_write(ret_handle, content)
            self.gagent.guest_file_flush(ret_handle)
            self.gagent.guest_file_close(ret_handle)

        def result_check_enforcing():
            """
            Can't open guest file via guest agent with different open-mode
            when selinux policy mode is enforcing.But can open temp file with
            append mode via guest agent
            """
            def check(guest_file, open_mode):
                error_context.context("Try to open %s with %s mode via"
                                      " guest agent in enforcing"
                                      " selinux policy." %
                                      (guest_file, open_mode),
                                      logging.info)
                if "/tmp" in guest_file and open_mode == "a+":
                    # can open and operate guest file successfully
                    file_operation(guest_file, open_mode)
                else:
                    try:
                        self.gagent.guest_file_open(guest_file,
                                                    mode=open_mode)
                    except guest_agent.VAgentCmdError as detail:
                        msg = r"failed to open file.*Permission denied"
                        if not re.search(msg, str(detail)):
                            test.fail("This is not the desired information: "
                                      "('%s')" % str(detail))
                    else:
                        test.fail("When selinux policy is 'Enforcing', guest"
                                  " agent should not open %s with %s mode." %
                                  (guest_file, open_mode))
            for ch_file in [guest_temp_file, guest_file]:
                check(ch_file, 'a+')
                check(ch_file, 'w+')

        def result_check_permissive():
            """
            Open guest file via guest agent with different open-mode
            when selinux policy mode is permissive.
            """
            def check(guest_file, open_mode):
                error_context.context("Try to open %s with %s mode via"
                                      " guest agent in permissive"
                                      " selinux policy." %
                                      (guest_file, open_mode),
                                      logging.info)
                # can open and operate guest file successfully
                file_operation(guest_file, open_mode)
            for ch_file in [guest_temp_file, guest_file]:
                check(ch_file, 'a+')
                check(ch_file, 'w+')

        content = "hello world\n"
        guest_temp_file = "/tmp/testqga"
        guest_file = "/home/testqga"
        session = self._get_session(self.params, None)
        self._open_session_list.append(session)
        logging.info("Change guest-file related cmd to white list.")
        self._change_bl(session)

        error_context.context("Create and write content to temp file and"
                              " non temp file.", logging.info)
        session.cmd("echo 'hello world' > %s" % guest_temp_file)
        session.cmd("echo 'hello world' > %s" % guest_file)

        error_context.context("Set selinux policy to 'Enforcing' mode in"
                              " guest.", logging.info)
        if session.cmd_output("getenforce").strip() != "Enforcing":
            session.cmd("setenforce 1")
        result_check_enforcing()

        error_context.context("Set selinux policy to 'Permissive' mode in"
                              " guest.", logging.info)
        session.cmd("setenforce 0")
        result_check_permissive()
        self._change_bl_back(session)

    @error_context.context_aware
    def gagent_check_guest_exec(self, test, params, env):
        """
        Execute a command in the guest via guest-exec cmd,
        and check status of this process.

        Steps:
        1) Change guest-exec related cmd to white list,linux guest only.
        2) Execute guest cmd and get the output.
        3) Check the cmd's result and output from return.
        4) Execute guest cmd and no need to get the output.
        5) Check the cmd's result from return.
        6) Issue an invalid guest cmd.
        7) Check the return result.
        8) Execute guest cmd with wrong args.
        9) Check the return result.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        """

        def _guest_cmd_run(guest_cmd, cmd_args=None, env_qga=None,
                           input=None, capture_output=None):
            """
            Execute guest-exec cmd and get the result in timeout.

            :param guest_cmd: path or executable name to execute
            :param cmd_args: argument list to pass to executable
            :param env_qga: environment variables to pass to executable
            :param input: data to be passed to process stdin (base64 encoded)
            :param capture_output: bool flag to enable capture of stdout/stderr
                                   of running process,defaults to false.
            :return: result of guest-exec cmd
            """

            # change cmd_args to be a list needed by guest-exec.
            if cmd_args:
                cmd_args = cmd_args.split()
            ret = self.gagent.guest_exec(path=guest_cmd, arg=cmd_args,
                                         env=env_qga, input_data=input,
                                         capture_output=capture_output)
            end_time = time.time() + float(params["guest_cmd_timeout"])
            while time.time() < end_time:
                result = self.gagent.guest_exec_status(ret["pid"])
                if result["exited"]:
                    logging.info("Guest cmd is finished.")
                    break
                time.sleep(5)

            if not result["exited"]:
                test.error("Guest cmd is still running, pls login guest to"
                           " handle it or extend your timeout.")
            # check the exitcode and output/error data if capture_output
            #  is true
            if capture_output is not True:
                return result
            if params.get("os_type") == "linux":
                if result["exitcode"] == 0:
                    if "out-data" in result:
                        out_data = base64.b64decode(result["out-data"]).\
                            decode()
                        logging.info("The guest cmd is executed successfully,"
                                     "the output is:\n%s." % out_data)
                    elif "err-data" in result:
                        test.fail("When exitcode is 0, should not return"
                                  " error data.")
                    else:
                        test.fail("There is no output with capture_output is true.")
                else:
                    if "out-data" in result:
                        test.fail("When exitcode is 1, should not return"
                                  " output data.")
                    elif "err-data" in result:
                        err_data = base64.b64decode(result["err-data"]).\
                            decode()
                        logging.info("The guest cmd failed,"
                                     "the error info is:\n%s" % err_data)
                    else:
                        test.fail("There is no output with capture_output is true.")
            else:
                # for windows guest,no matter what exitcode is,
                #  the return key is out-data
                if "out-data" in result:
                    out_data = base64.b64decode(result["out-data"]).decode()
                    logging.info("The guest cmd is executed successfully,"
                                 "the output is:\n%s." % out_data)
                else:
                    test.fail("There is no output with capture_output is true.")
            return result

        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)

        error_context.context("Change guest-exec related cmd to white list.",
                              logging.info)
        self._change_bl(session)

        guest_cmd = params["guest_cmd"]
        guest_cmd_args = params["guest_cmd_args"]

        error_context.context("Execute guest cmd and get the output.",
                              logging.info)
        result = _guest_cmd_run(guest_cmd=guest_cmd, cmd_args=guest_cmd_args,
                                capture_output=True)

        if "out-data" not in result and "err-data" not in result:
            test.fail("There is no output in result.")

        error_context.context("Execute guest cmd and no need to get the output.",
                              logging.info)
        result = _guest_cmd_run(guest_cmd=guest_cmd, cmd_args=guest_cmd_args)

        if "out-data" in result or "err-data" in result:
            test.fail("There is output in result which is not expected.")

        error_context.context("Invalid guest cmd test.", logging.info)
        try:
            self.gagent.guest_exec(path="invalid_cmd")
        except guest_agent.VAgentCmdError as detail:
            if not re.search('Failed to execute child process', str(detail)):
                test.fail("This is not the desired information: ('%s')"
                          % str(detail))
        else:
            test.fail("Should not success for invalid cmd.")

        error_context.context("Execute guest cmd with wrong args.", logging.info)
        if params.get("os_type") == "linux":
            guest_cmd = "cd"
            guest_cmd_args = "/tmp/qga_empty_dir"
        else:
            guest_cmd = "ping"
            guest_cmd_args = "invalid-address"
        result = _guest_cmd_run(guest_cmd=guest_cmd, cmd_args=guest_cmd_args,
                                capture_output=True)
        if result["exitcode"] == 0:
            test.fail("The cmd should be failed with wrong args.")
        self._change_bl_back(session)

    @error_context.context_aware
    def _action_before_fsfreeze(self, *args):
        session = self._get_session(self.params, None)
        session.cmd("restorecon -Rv /", timeout=180)
        self._open_session_list.append(session)

    @error_context.context_aware
    def _action_after_fsfreeze(self, *args):
        error_context.context("Verfiy FS is frozen in guest.", logging.info)

        if not self._open_session_list:
            self.test.error("Could not find any opened session")
        # Use the last opened session to send cmd.
        session = self._open_session_list[-1]

        try:
            session.cmd(args[0], args[1])
        except aexpect.ShellTimeoutError:
            logging.info("FS is frozen as expected,can't write in guest.")
        else:
            self.test.fail("FS is not frozen,still can write in guest.")

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
            session.cmd(args[0], args[1])
        except aexpect.ShellTimeoutError:
            self.test.fail("FS is not thawed, still can't write in guest.")
        else:
            logging.info("FS is thawed as expected, can write in guest.")

    @error_context.context_aware
    def _fsfreeze(self, fsfreeze_list=False, mountpoints=None,
                  check_mountpoints=None):
        """
        Test guest agent commands "guest-fsfreeze-freeze/status/thaw/
        fsfreeze-list"

        Test steps:
        1) Check the FS is thawed.
        2) Freeze the FS.
        3) Check the FS is frozen from both guest agent side and
         guest os side.
        4) Thaw the FS.
        5) Check the FS is unfrozen from both guest agent side and
         guest os side.

        :param fsfreeze_list: Freeze fs with guest-fsfreeze-freeze or
                              guest-fsfreeze-freeze-list
        :param mountpoints: an array of mountpoints of filesystems to be frozen.
                            it's the parameter for guest-fsfreeze-freeze-list.
                            if omitted, every mounted filesystem is frozen
        :param check_mountpoints: an array of mountpoints, to check if they are
                                  frozen/thaw, used to the following two sceanrio.
                                  a.fsfreeze_list is true and mountpoints is none.
                                  b.fsfreeze_list is true and mountpoints has
                                    invalid value and valide value(only linux guest)
        """
        write_cmd = self.params.get("gagent_fs_test_cmd", "")
        write_cmd_timeout = int(self.params.get("write_cmd_timeout", 60))
        try:
            expect_status = self.gagent.FSFREEZE_STATUS_THAWED
            self.gagent.verify_fsfreeze_status(expect_status)
        except guest_agent.VAgentFreezeStatusError:
            # Thaw guest FS if the fs status is incorrect.
            self.gagent.fsthaw(check_status=False)

        self._action_before_fsfreeze()
        error_context.context("Freeze the FS when fsfreeze_list is"
                              " %s and mountpoints is %s." %
                              (fsfreeze_list, mountpoints), logging.info)
        self.gagent.fsfreeze(fsfreeze_list=fsfreeze_list,
                             mountpoints=mountpoints)
        try:
            if fsfreeze_list:
                if check_mountpoints:
                    # only for invalid mount_points
                    # or mountpoints is none
                    mountpoints = check_mountpoints
                write_cmd_list = []
                for mpoint in mountpoints:
                    mpoint = "/tmp" if mpoint == "/" else mpoint
                    write_cmd_m = write_cmd % mpoint
                    write_cmd_list.append(write_cmd_m)
                write_cmd_guest = ";".join(write_cmd_list)
            else:
                mountpoint_def = self.params["mountpoint_def"]
                write_cmd_guest = write_cmd % mountpoint_def

            self._action_after_fsfreeze(write_cmd_guest, write_cmd_timeout)
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
        # check after fsthaw
        self._action_after_fsthaw(write_cmd_guest, write_cmd_timeout)

    @error_context.context_aware
    def gagent_check_fsfreeze(self, test, params, env):
        """
        Test guest agent commands "guest-fsfreeze-freeze"

        Test steps:
        1) Check the FS is thawed.
        2) Freeze the FS.
        3) Check the FS is frozen from both guest agent side and
         guest os side.
        4) Thaw the FS.
        5) Check the FS is unfrozen from both guest agent side and
         guest os side.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environmen.
        """
        self._fsfreeze()

    @error_context.context_aware
    def gagent_check_fsfreeze_list(self, test, params, env):
        """
        Test guest agent commands "guest-fsfreeze-freeze-list"

        Test steps:
        1) Check the FS is thawed.
        2) Freeze the FS without mountpoint.
        3) Check the FS is frozen from both guest agent side and
         guest os side.
        4) Thaw the FS.
        5) Check the FS is unfrozen from both guest agent side and
         guest os side.
        6) Freeze the FS with one valid mountpoint.
        7) repeate step4-5.
        8) Freeze the FS with two valid mountpoints
        9) repeate step4-5.
        8) Freeze the FS with one valid mountpoint and
         one invalid mountpoint.
        9) Check the result.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environmen.
        """
        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)
        image_size_stg0 = params["image_size_stg0"]

        error_context.context("Format the new data disk and mount it.",
                              logging.info)
        if params.get("os_type") == "linux":
            self.gagent_setsebool_value('on', params, self.vm)
            disk_data = list(utils_disk.get_linux_disks(session).keys())
            mnt_point_data = utils_disk.configure_empty_disk(
                session, disk_data[0], image_size_stg0, "linux",
                labeltype="msdos")[0]
            mount_points = ["/", mnt_point_data]
        else:
            disk_index = utils_misc.wait_for(
                lambda: utils_disk.get_windows_disks_index(session,
                                                           image_size_stg0),
                120)
            if disk_index:
                logging.info("Clear readonly for disk and online it in"
                             " windows guest.")
                if not utils_disk.update_windows_disk_attributes(session,
                                                                 disk_index):
                    test.error("Failed to update windows disk attributes.")
                mnt_point_data = utils_disk.configure_empty_disk(
                    session, disk_index[0], image_size_stg0, "windows",
                    labeltype="msdos")[0]
                mount_points = ["C:\\", "%s:\\" % mnt_point_data]
            else:
                test.error("Didn't find any disk_index except system disk.")

        error_context.context("Freeze fs without parameter of mountpoints.",
                              logging.info)
        self._fsfreeze(fsfreeze_list=True, check_mountpoints=mount_points)
        error_context.context("Freeze fs with two mount point.",
                              logging.info)
        self._fsfreeze(fsfreeze_list=True, mountpoints=mount_points)
        error_context.context("Freeze fs with every mount point.",
                              logging.info)
        for mpoint in mount_points:
            mpoint = ["%s" % mpoint]
            self._fsfreeze(fsfreeze_list=True, mountpoints=mpoint)

        error_context.context("Freeze fs with one valid mountpoint and"
                              " one invalid mountpoint.", logging.info)
        if params.get("os_type") == "linux":
            mount_points_n = ["/", "/invalid"]
            check_mp = ["/"]
            self._fsfreeze(fsfreeze_list=True, mountpoints=mount_points_n,
                           check_mountpoints=check_mp)
            self.gagent_setsebool_value('off', params, self.vm)
        else:
            mount_points_n = ["C:\\", "X:\\"]
            logging.info("Make sure the current status is thaw.")
            try:
                expect_status = self.gagent.FSFREEZE_STATUS_THAWED
                self.gagent.verify_fsfreeze_status(expect_status)
            except guest_agent.VAgentFreezeStatusError:
                # Thaw guest FS if the fs status is incorrect.
                self.gagent.fsthaw(check_status=False)
            try:
                self.gagent.fsfreeze(fsfreeze_list=True,
                                     mountpoints=mount_points_n)
            except guest_agent.VAgentCmdError as e:
                expected = "failed to add X:\\ to snapshot set"
                if expected not in e.edata["desc"]:
                    test.fail(e)
            else:
                test.fail("Cmd 'guest-fsfreeze-freeze-list' is executed"
                          " successfully, but it should return error.")
            finally:
                if self.gagent.get_fsfreeze_status() == \
                        self.gagent.FSFREEZE_STATUS_FROZEN:
                    self.gagent.fsthaw(check_status=False)

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
            self.vm.devices.simple_unplug(devs[-1], self.vm.monitor)
        finally:
            if self.gagent.get_fsfreeze_status() == self.gagent.FSFREEZE_STATUS_FROZEN:
                try:
                    self.gagent.fsthaw(check_status=False)
                except guest_agent.VAgentCmdError as detail:
                    if not re.search("fsfreeze is limited up to 10 seconds", str(detail)):
                        test.error("guest-fsfreeze-thaw cmd failed with:"
                                   "('%s')" % str(detail))
            self.vm.verify_alive()
            if params.get("os_type") == "linux":
                utils_disk.umount(new_disks[0], mnt_point[0], session=session)
            session.close()

    @error_context.context_aware
    def gagent_check_path_fsfreeze_hook(self, test, params, env):
        """
        Check fsfreeze-hook path in man page and qemu-ga help

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment
        """
        session = self._get_session(params, self.vm)
        self.gagent_stop(session, self.vm)
        error_context.context("Start gagent with -F option", logging.info)
        self.gagent_start(session, self.vm)

        error_context.context("Get the default path of fsfreeze-hook in"
                              " qemu-ga help.", logging.info)
        s, o = session.cmd_status_output(params["cmd_get_help_info"])
        help_cmd_hook_path = o.strip().replace(')', '').split()[-1]

        error_context.context("Get the default path of fsfreeze-hook in"
                              " man page.", logging.info)
        logging.info("Export qemu-ga man page to guest file.")
        qga_man_file = "/tmp/man_file"
        session.cmd(params["cmd_get_man_page"] % qga_man_file)

        logging.info("Get fsfreeze-hook script default path in the file.")
        cmd_get_hook_path = r'cat %s |grep /fsfreeze-hook' % qga_man_file
        output = session.cmd_output(cmd_get_hook_path).strip()
        hook_pattern = r'/etc.*fsfreeze-hook'
        man_cmd_hook_path = re.findall(hook_pattern, output, re.I)[0]
        # the expected hook path
        hook_path_expected = "/etc/qemu-kvm/fsfreeze-hook"
        if help_cmd_hook_path != hook_path_expected \
                or man_cmd_hook_path != hook_path_expected:
            msg = "The hook path is not correct in qemu-ga -h or man page\n"
            msg += "it's in help cmd is %s\n" % help_cmd_hook_path
            msg += "it's in man page is %s\n" % man_cmd_hook_path
            test.fail(msg)
        session.cmd("rm -rf %s" % qga_man_file)

    @error_context.context_aware
    def gagent_check_fsfreeze_hook_script(self, test, params, env):
        """
        During fsfreeze,verify fsfreeze hook script works.

        Steps:
        1) Check fsfreeze hook related files.
        2) Check fsfreeze hook path set in qemu-ga config file.
        3) Fsfreeze hook should be with '-x' permission for all users.
        4) Verify agent service is using the fsfreeze hook.
        5) Create a simple user script in hook scripts path.
        6) Get fsfreeze hook log file.
        7) Issue freeze & thaw cmds.
        8) Check fsfreeze hook logs.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment
        """

        def log_check(action):
            msg = "testing %s:%s" % (user_script_path, action)
            hook_log = session.cmd_output("cat %s" % log_path)
            if msg not in hook_log.strip().splitlines()[-2]:
                test.fail("Fsfreeze hook test failed\nthe fsfreeze"
                          " hook log is %s." % hook_log)

        session = self._get_session(self.params, None)
        self._open_session_list.append(session)

        error_context.context("Checking fsfreeze hook related scripts.",
                              logging.info)
        cmd_get_hook_files = "rpm -ql qemu-guest-agent |grep fsfreeze-hook"
        hook_files = session.cmd_output(cmd_get_hook_files)

        if len(hook_files.strip().split()) != 5:
            test.fail("Fsfreeze hook files are missed, the output is"
                      " %s" % hook_files)

        error_context.context("Checking fsfreeze hook path set in config"
                              " file.", logging.info)
        config_file = "/etc/sysconfig/qemu-ga"
        cmd_get_hook_path = "cat %s | grep" \
                            " ^FSFREEZE_HOOK_PATHNAME" % config_file
        o_path = session.cmd_output(cmd_get_hook_path)
        hook_path = o_path.strip().split("=")[1]

        detail = session.cmd_output("ll %s" % hook_path)
        if not re.search(r".*x.*x.*x", detail):
            test.fail("Not all users have executable permission"
                      " of fsfreeze hook, the detail is %s." % detail)

        error_context.context("Checking if agent service is using the"
                              " fsfreeze hook.", logging.info)
        cmd_get_hook = "ps aux |grep /usr/bin/qemu-ga |grep fsfreeze-hook"
        hook_path_info = session.cmd_output(cmd_get_hook).strip()
        if params['os_variant'] == 'rhel6':
            error_context.context("For rhel6 guest,need to enable fsfreeze"
                                  " hook and restart agent service.",
                                  logging.info)
            if not session.cmd_output(cmd_get_hook):
                cmd_enable_hook = "sed -i 's/FSFREEZE_HOOK_ENABLE=0/" \
                                  "FSFREEZE_HOOK_ENABLE=1/g' %s" % \
                                  config_file
                session.cmd(cmd_enable_hook)
                session.cmd(params["gagent_restart_cmd"])
                hook_path_info = session.cmd_output(cmd_get_hook).strip()
            hook_path_service = hook_path_info.split("--fsfreeze-hook=")[-1]
        else:
            hook_path_service = hook_path_info.split("-F")[-1]

        if hook_path_service != hook_path:
            test.fail("Fsfreeze hook in qemu-guest-agent service is different"
                      " from config.\nit's %s from service\n"
                      "it's %s from config." % (hook_path_service, hook_path))

        error_context.context("Create a simple script to verify fsfreeze"
                              " hook.", logging.info)
        cmd_get_user_path = "rpm -ql qemu-guest-agent |grep fsfreeze-hook.d" \
                            " |grep -v /usr/share"
        output = session.cmd_output(cmd_get_user_path)
        user_script_path = output.strip().split("\n")[-1]
        user_script_path += "/user_script.sh"

        cmd_create_script = 'echo "printf \'testing %%s:%%s\\n\' \\$0 \\$@"' \
                            ' > %s' % user_script_path
        session.cmd(cmd_create_script)
        session.cmd("chmod +x %s" % user_script_path)

        error_context.context("Issue fsfreeze and thaw commands and check"
                              " logs.", logging.info)
        cmd_get_log_path = "cat %s |grep ^LOGFILE" % hook_path
        log_path = session.cmd_output(cmd_get_log_path).strip().split("=")[-1]
        self.gagent.fsfreeze()
        log_check("freeze")
        self.gagent.fsthaw()
        log_check("thaw")

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

    @error_context.context_aware
    def gagent_check_qgastatus_after_remove_qga(self, test, params, env):
        """
        Check the qga.service status after removing qga.
        """
        session = self._get_session(self.params, None)
        self._open_session_list.append(session)

        error_context.context("Remove qga.service.", logging.info)
        self.gagent_uninstall(session, self.vm)

        error_context.context("Check qga.service after removing it.", logging.info)
        try:
            if self._check_ga_service(session, params.get("gagent_status_cmd")):
                test.fail("QGA service should be removed.")
        finally:
            error_context.context("Recover test env that start qga.", logging.info)
            self.gagent_install(session, self.vm)
            self.gagent_start(session, self.vm)
            self.gagent_verify(params, self.vm)

    @error_context.context_aware
    def gagent_check_frozen_io(self, test, params, env):
        """
        fsfreeze test during disk io.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment
        """
        error_context.context("Before freeze/thaw the FS, run the iozone test",
                              logging.info)
        session = self._get_session(self.params, None)
        self._open_session_list.append(session)
        iozone_cmd = utils_misc.set_winutils_letter(session, params["iozone_cmd"])
        session.cmd(iozone_cmd, timeout=360)
        error_context.context("Freeze the FS.", logging.info)
        try:
            self.gagent.fsfreeze()
        except guest_agent.VAgentCmdError as detail:
            if not re.search("timeout when try to receive Frozen event from"
                             " VSS provider", str(detail)):
                test.fail("guest-fsfreeze-freeze cmd failed with:"
                          "('%s')" % str(detail))
        if self.gagent.verify_fsfreeze_status(self.gagent.FSFREEZE_STATUS_FROZEN):
            try:
                self.gagent.fsthaw(check_status=False)
            except guest_agent.VAgentCmdError as detail:
                if not re.search("fsfreeze is limited up to 10 seconds", str(detail)):
                    test.error("guest-fsfreeze-thaw cmd failed with:"
                               "('%s')" % str(detail))

        self.gagent_verify(self.params, self.vm)

    @error_context.context_aware
    def gagent_check_vss_status(self, test, params, env):
        """
        Only for windows guest,check QEMU Guest Agent VSS Provider service start type
        and if it works.

        Steps:
        1) Check VSS Provider service start type.
        2) Check VSS Provider service should be in stopped status.
        3) Issue fsfreeze qga command.
        4) Check VSS Provider service should be in running status.
        5) Issue fsthaw qga command.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment
        """
        def check_vss_info(cmd_type, key, expect_value):
            cmd_vss = "sc %s \"QEMU Guest Agent VSS Provider\" | findstr /i %s" % \
                      (cmd_type, key)
            status, output = session.cmd_status_output(cmd_vss)
            if status:
                test.error("Command to check VSS service info failed,"
                           "detailed info is:\n%s" % output)
            vss_result = output.split()[-1]
            if vss_result != expect_value:
                test.fail("The output is %s which is not expected."
                          % vss_result)

        session = self._get_session(self.params, None)
        self._open_session_list.append(session)

        error_context.context("Check VSS Provider service start type.",
                              logging.info)
        check_vss_info("qc", "START_TYPE", "DEMAND_START")

        error_context.context("Check VSS Provider status.", logging.info)
        check_vss_info("query", "STATE", "STOPPED")

        error_context.context("Freeze fs.", logging.info)
        self.gagent.fsfreeze()

        error_context.context("Check VSS Provider status after fsfreeze.", logging.info)
        check_vss_info("query", "STATE", "RUNNING")

        error_context.context("Thaw fs.", logging.info)
        try:
            self.gagent.fsthaw()
        except guest_agent.VAgentCmdError as detail:
            if not re.search("fsfreeze is limited up to 10 seconds", str(detail)):
                test.error("guest-fsfreeze-thaw cmd failed with:"
                           "('%s')" % str(detail))

    @error_context.context_aware
    def gagent_check_fsinfo(self, test, params, env):
        """
        Execute "guest-fsinfo" command to guest agent,check file system of
        mountpoint,disk's name and serial number.

        steps:
        1) Check filesystem usage statistics
        2) check file system type of every mount point.
        3) check disk name.
        4) check disk's serial number.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.

        """
        def qga_guest_diskusage(mountpoint):
            """
            Send cmd in guest to get disk usage.
            :param mountpoint: the mountpoint of filesystem
            """
            cmd_get_diskusage = params["cmd_get_disk_usage"] % mountpoint
            disk_usage_guest = session.cmd(cmd_get_diskusage).strip().split()
            disk_total_guest = int(disk_usage_guest[0])
            if params["os_type"] == "windows":
                # Just can get total and freespace disk usage from windows.
                disk_freespace_guest = int(disk_usage_guest[1])
                disk_used_guest = int(disk_total_guest - disk_freespace_guest)
            else:
                disk_used_guest = int(disk_usage_guest[1])
            disk_total_qga = int(fs["total-bytes"])
            disk_used_qga = int(fs["used-bytes"])
            diff_total_qga_guest = abs(disk_total_guest - disk_total_qga)
            diff_used_qga_guest = abs(disk_used_guest - disk_used_qga)
            return (diff_total_qga_guest, diff_used_qga_guest)

        def check_usage_qga_guest(mount_point):
            """
            Contrast disk usage from guest and qga that needed
            to call previous function 'qga_guest_diskusage'.
            :param mountpoint: the mountpoint of filesystem
            """
            disk_usage_guest = qga_guest_diskusage(mount_point)
            diff_total_qgaguest = int(disk_usage_guest[0])
            diff_used_qgaguest = int(disk_usage_guest[1])
            if diff_total_qgaguest != 0:
                test.fail("File System %s Total bytes doesn't match." %
                          mount_point)
            if diff_used_qgaguest != 0:
                if mount_point != 'C:' and mount_point != '/':
                    test.fail("File system %s used bytes doesn't match." %
                              mount_point)
                else:
                    # Disk 'C:' and '/' used space usage have a floating interval,
                    # so set a safe value '10485760'.
                    logging.info("Need to check the floating interval for C: or /.")
                    if diff_used_qgaguest > 10485760:
                        test.fail("File System floating interval is too large,"
                                  "Something must go wrong.")
                    else:
                        logging.info("File system '%s' usages are within the safe "
                                     "floating range." % mount_point)

        session = self._get_session(params, None)
        self._open_session_list.append(session)
        serial_num = params["blk_extra_params_image1"].split("=")[1]

        error_context.context("Check all file system info in a loop.", logging.info)
        fs_info_qga = self.gagent.get_fsinfo()
        for fs in fs_info_qga:
            device_id = fs["name"]
            mount_pt = fs["mountpoint"]
            if (params["os_type"] == "windows" and
                    mount_pt != "System Reserved"):
                mount_pt = mount_pt[:2]

            error_context.context("Check file system '%s' usage statistics." %
                                  mount_pt, logging.info)
            if mount_pt != 'System Reserved':
                # disk usage statistic for System Reserved
                # volume is not supported.
                check_usage_qga_guest(mount_pt)
            else:
                logging.info("'%s' disk usage statistic is not supported" % mount_pt)

            error_context.context("Check file system type of '%s' mount point." %
                                  mount_pt, logging.info)
            fs_type_qga = fs["type"]
            cmd_get_disk = params["cmd_get_disk"] % mount_pt.replace("/", r"\/")
            if params["os_type"] == "windows":
                cmd_get_disk = params["cmd_get_disk"] % device_id.replace("\\", r"\\")
            disk_info_guest = session.cmd(cmd_get_disk).strip().split()
            fs_type_guest = disk_info_guest[1]
            if fs_type_qga != fs_type_guest:
                test.fail("File System doesn't match.\n"
                          "from guest-agent is %s.\nfrom guest os is %s."
                          % (fs_type_qga, fs_type_guest))
            else:
                logging.info("File system type is %s which is expected." % fs_type_qga)

            error_context.context("Check disk name.", logging.info)
            disk_name_qga = fs["name"]
            disk_name_guest = disk_info_guest[0]
            if params["os_type"] == "linux":
                if not re.findall(r'^/\w*/\w*$', disk_name_guest):
                    disk_name_guest = session.cmd("readlink %s" % disk_name_guest).strip()
                disk_name_guest = disk_name_guest.split('/')[-1]
            if disk_name_qga != disk_name_guest:
                test.fail("Device name doesn't match.\n"
                          "from guest-agent is %s.\nit's from guest os is %s."
                          % (disk_name_qga, disk_name_guest))
            else:
                logging.info("Disk name is %s which is expected." % disk_name_qga)

            error_context.context("Check serial number of some disk.", logging.info)
            if fs_type_qga == "UDF" or fs_type_qga == "CDFS":
                logging.info("Only check block disk's serial info, no cdrom.")
                continue
            serial_qga = fs["disk"][0]["serial"]
            if not re.findall(serial_num, serial_qga):
                test.fail("Serial name is not correct via qga.\n"
                          "from guest-agent is %s.\n"
                          "but it should include %s." % (serial_qga, serial_num))
            else:
                logging.info("Serial number is %s which is expected." % serial_qga)

    @error_context.context_aware
    def gagent_check_nonexistent_cmd(self, test, params, env):
        """
        Execute "guest-fsinfo" command to guest agent, and check
        the return info.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        session = self._get_session(params, None)
        self._open_session_list.append(session)
        error_context.context("Issue the no existed guest-agent "
                              "cmd via qga.", logging.info)
        cmd_wrong = params["wrong_cmd"]
        try:
            self.gagent.cmd(cmd_wrong)
        except guest_agent.VAgentCmdError as detail:
            pattern = "command %s has not been found" % cmd_wrong
            if not re.search(pattern, str(detail), re.I):
                test.fail("The error info is not correct, the return is"
                          " %s." % str(detail))
        else:
            test.fail("Should return error info.")

    @error_context.context_aware
    def gagent_check_log(self, test, params, env):
        """
        Check guest agent logs.
        Steps:
        1) start guest-agent to record logs
        2) issue some guest agent commands
        3) check agent log, if those commands are recorded

        :param test: kvm test object
        :param params: Dictionary with the test parameterspy
        :param env: Dictionary with test environment.
        """
        def log_check(qga_cmd):
            """
            check guest agent log.
            """
            error_context.context("Check %s cmd in agent log." % qga_cmd,
                                  logging.info)
            log_str = session.cmd_output(get_log_cmd).strip().split('\n')[-1]
            pattern = r"%s" % qga_cmd
            if not re.findall(pattern, log_str, re.M | re.I):
                test.fail("The %s command is not recorded in agent"
                          " log." % qga_cmd)

        get_log_cmd = params["get_log_cmd"]
        session = self._get_session(self.params, self.vm)
        self._open_session_list.append(session)
        self._change_bl(session)

        error_context.context("Issue some common guest agent commands.",
                              logging.info)
        self.gagent.get_time()
        log_check("guest-get-time")

        tmp_file = params["tmp_file"]
        content = "hello world\n"
        ret_handle = int(self.gagent.guest_file_open(tmp_file, mode="w+"))
        log_check("guest-file-open")

        self.gagent.guest_file_write(ret_handle, content)
        log_check("guest-file-write")

        self.gagent.guest_file_read(ret_handle)
        log_check("guest-file-read")
        self._change_bl_back(session)

    @error_context.context_aware
    def gagent_check_with_migrate(self, test, params, env):
        """
        Migration test with guest agent service running.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        error_context.context("Migrate guest while guest agent service is"
                              " running.", logging.info)
        qemu_migration.set_speed(self.vm, params.get("mig_speed", "1G"))
        self.vm.migrate()
        error_context.context("Recreate a QemuAgent object after vm"
                              " migration.", logging.info)
        self.gagent = None
        args = [params.get("gagent_serial_type"), params.get("gagent_name")]
        self.gagent_create(params, self.vm, *args)
        error_context.context("Verify if guest agent works.", logging.info)
        self.gagent_verify(self.params, self.vm)

    @error_context.context_aware
    def gagent_check_umount_frozen(self, test, params, env):
        """
        Umount file system while fs freeze.

        Steps:
        1) boot guest with a new data storage.
        2) format disk and mount it.
        3) freeze fs.
        4) umount fs/offline the volume in guest,
           for rhel6 guest will umount fail.
        5) thaw fs.
        6) mount fs and online it again.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment
        """
        def wrap_windows_cmd(cmd):
            """
            add header and footer for cmd in order to run it in diskpart tool.

            :param cmd: cmd to be wrapped.
            :return: wrapped cmd
            """
            disk = "disk_" + ''.join(random.sample(string.ascii_letters +
                                                   string.digits, 4))
            cmd_header = "echo list disk > " + disk
            cmd_header += " && echo select disk %s >> " + disk
            cmd_footer = " echo exit >> " + disk
            cmd_footer += " && diskpart /s " + disk
            cmd_footer += " && del /f " + disk
            cmd += " >> " + disk
            return " && ".join([cmd_header, cmd, cmd_footer])

        session = self._get_session(params, self.vm)
        self._open_session_list.append(session)
        image_size_stg0 = params["image_size_stg0"]

        error_context.context("Format the new data disk and mount it.",
                              logging.info)
        if params.get("os_type") == "linux":
            self.gagent_setsebool_value('on', params, self.vm)
            disk_data = list(utils_disk.get_linux_disks(session).keys())
            mnt_point = utils_disk.configure_empty_disk(
                session, disk_data[0], image_size_stg0, "linux",
                labeltype="msdos")
            src = "/dev/%s1" % disk_data[0]
        else:
            disk_index = utils_misc.wait_for(
                lambda: utils_disk.get_windows_disks_index(session,
                                                           image_size_stg0),
                120)
            if disk_index:
                logging.info("Clear readonly for disk and online it in windows"
                             " guest.")
                if not utils_disk.update_windows_disk_attributes(session,
                                                                 disk_index):
                    test.error("Failed to update windows disk attributes.")
                mnt_point = utils_disk.configure_empty_disk(
                    session, disk_index[0], image_size_stg0, "windows",
                    labeltype="msdos")
            else:
                test.error("Didn't find any disk_index except system disk.")

        error_context.context("Freeze fs.", logging.info)
        session.cmd("restorecon -Rv /", timeout=180)
        self.gagent.fsfreeze()

        error_context.context("Umount fs or offline disk in guest.",
                              logging.info)
        if params.get("os_type") == "linux":
            if params['os_variant'] == 'rhel6':
                try:
                    session.cmd("umount %s" % mnt_point[0])
                except ShellTimeoutError:
                    logging.info("For rhel6 guest, umount fs will fail after"
                                 " fsfreeze.")
                else:
                    test.error("For rhel6 guest, umount fs should fail after"
                               " fsfreeze.")
            else:
                if not utils_disk.umount(src, mnt_point[0], session=session):
                    test.fail("For rhel7+ guest, umount fs should success"
                              " after fsfreeze.")
        else:
            detail_cmd = ' echo detail disk'
            detail_cmd = wrap_windows_cmd(detail_cmd)
            offline_cmd = ' echo offline disk'
            offline_cmd = wrap_windows_cmd(offline_cmd)
            did = disk_index[0]
            logging.info("Detail for 'Disk%s'" % did)
            details = session.cmd_output(detail_cmd % did)
            if re.search("Status.*Online", details, re.I | re.M):
                logging.info("Offline 'Disk%s'" % did)
                status, output = session.cmd_status_output(offline_cmd % did,
                                                           timeout=120)
                if status != 0:
                    test.fail("Can not offline disk: %s with"
                              " fsfreeze." % output)

        error_context.context("Thaw fs.", logging.info)
        try:
            self.gagent.fsthaw()
        except guest_agent.VAgentCmdError as detail:
            if not re.search("fsfreeze is limited up to 10 seconds",
                             str(detail)):
                test.error("guest-fsfreeze-thaw cmd failed with: ('%s')"
                           % str(detail))

        error_context.context("Mount fs or online disk in guest.",
                              logging.info)
        if params.get("os_type") == "linux":
            try:
                if not utils_disk.mount(src, mnt_point[0], session=session):
                    if params['os_variant'] != 'rhel6':
                        test.fail("For rhel7+ guest, mount fs should success"
                                  " after fsthaw.")
                else:
                    if params['os_variant'] == 'rhel6':
                        test.fail("For rhel6 guest, mount fs should fail after"
                                  " fsthaw.")
            finally:
                self.gagent_setsebool_value('off', params, self.vm)
        else:
            if not utils_disk.update_windows_disk_attributes(session,
                                                             disk_index):
                test.fail("Can't online disk with fsthaw")

    @error_context.context_aware
    def gagent_check_user_logoff(self, test, params, env):
        """
        Check guest agent status when user is logged out.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        session = self._get_session(params, None)
        self._open_session_list.append(session)

        error_context.context("Check which user is logged in.", logging.info)
        user_info = session.cmd_output('query user | findstr /i "Active"')
        login_user_id = user_info.strip().split()[2]

        error_context.context("Make the user log out.", logging.info)
        try:
            session.cmd("logoff %s" % login_user_id)
        except aexpect.ShellProcessTerminatedError as detail:
            if not re.search("Connection reset by peer", str(detail)):
                test.error("Error occured with %s." % str(detail))
        else:
            test.fail("The user logoff failed.")

        error_context.context("Verify if guest agent works.", logging.info)
        self.gagent_verify(self.params, self.vm)

    @error_context.context_aware
    def gagent_check_blacklist(self, test, params, env):
        """
        Verify the blacklist of config file, linux guest only

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        def bl_check(qga_cmd):
            """
            check if qga cmd is disabled.
            """
            try:
                if qga_cmd == "guest-file-open":
                    self.gagent.guest_file_open(guest_file, mode="a+")
                else:
                    self.gagent.cmd(qga_cmd)
            except guest_agent.VAgentCmdError as detail:
                if re.search("%s has been disabled" % qga_cmd, str(detail)):
                    logging.info("%s cmd is disabled." % qga_cmd)
                else:
                    test.fail("%s cmd failed with:"
                              "('%s')" % (qga_cmd, str(detail)))
            else:
                test.fail("%s cmd is not in blacklist,"
                          " pls have a check." % qga_cmd)

        session = self._get_session(params, None)
        self._open_session_list.append(session)

        error_context.context("Try to execute guest-file-open command which"
                              " is in blacklist by default.", logging.info)

        randstr = utils_misc.generate_random_string(5)
        guest_file = "/tmp/qgatest" + randstr
        bl_check("guest-file-open")

        error_context.context("Try to execute guest-info command which is"
                              " not in blacklist.",
                              logging.info)
        self.gagent.cmd("guest-info")

        error_context.context("Change command in blacklist and restart"
                              " agent service.", logging.info)
        session.cmd("cp /etc/sysconfig/qemu-ga /etc/sysconfig/qemu-ga-bk")
        try:
            session.cmd(params["black_list_change_cmd"])
            session.cmd(params["gagent_restart_cmd"])

            error_context.context("Try to execute guest-file-open and "
                                  "guest-info commands again.", logging.info)
            ret_handle = int(self.gagent.guest_file_open(guest_file,
                                                         mode="a+"))
            self.gagent.guest_file_close(ret_handle)
            bl_check("guest-info")
        finally:
            session.cmd("rm -rf %s" % guest_file)
            cmd = "mv -f /etc/sysconfig/qemu-ga-bk /etc/sysconfig/qemu-ga"
            session.cmd(cmd)

    @error_context.context_aware
    def gagent_check_virtio_device(self, test, params, env):
        """
        check virtio device in windows guest.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        session = self._get_session(params, None)
        self._open_session_list.append(session)

        def _result_check(rsult_qga, rsult_guest):
            if rsult_qga != rsult_guest:
                msg = "The result is different between qga and guest\n"
                msg += "from qga: %s\n" % rsult_qga
                msg += "from guest: %s\n" % rsult_guest
                test.fail(msg)

        devs_list = self.gagent.get_virtio_device()
        check_driver_cmd_org = params["check_driver_powershell_cmd"]
        for device in devs_list:
            driver_name = device["driver-name"]
            error_context.context("Check %s info." % driver_name, logging.info)

            driver_date = device["driver-date"]
            driver_version = device["driver-version"]
            device_address = device["address"]["data"]
            device_id = device_address["device-id"]
            vendor_id = device_address["vendor-id"]

            filter_name = "friendlyname" if "Ethernet" in driver_name \
                else "devicename"
            check_driver_cmd = check_driver_cmd_org % (filter_name, driver_name)

            driver_info_guest = session.cmd_output(check_driver_cmd)
            # check driver date
            # driverdate    : 20200219000000.******+***
            date_group = re.search(r"driverdate.*\:\s(\d{4})(\d{2})(\d{2})",
                                   driver_info_guest, re.I).groups()
            driver_date_guest = "-".join(date_group)
            _result_check(driver_date, driver_date_guest)

            # check driver version
            driver_ver_guest = re.search(r"driverversion.*\:\s(\S+)",
                                         driver_info_guest, re.I).group(1)
            _result_check(driver_version, driver_ver_guest)

            # check vender id and device id
            pattern_dev = r"deviceid.*VEN_([A-Za-z0-9]+)&DEV_([A-Za-z0-9]+)&"
            id_dev = re.search(pattern_dev, driver_info_guest, re.I)
            vender_id_guest = int(id_dev.group(1), 16)
            device_id_guest = int(id_dev.group(2), 16)
            _result_check(vendor_id, vender_id_guest)
            _result_check(device_id, device_id_guest)

    @error_context.context_aware
    def gagent_check_os_basic_info(self, test, params, env):
        """
        Get hostname, timezone and currently active users on the vm.
        Steps:
        1) Check host name.
        2) Check host name after setting new host name
        3) Check timezone name.
        4) check timezone's offset to UTS in seconds.
        5) Check all active users number.
        6) Check every user info.
        7) Check every user's domain(windows only)
        8) Get the earlier loggin time for the same user.
        9) Check the login time for every user.
        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        session = self._get_session(params, None)
        self._open_session_list.append(session)

        def _result_check(rsult_qga, rsult_guest):
            if rsult_qga != rsult_guest:
                msg = "The result is different between qga and guest\n"
                msg += "from qga: %s\n" % rsult_qga
                msg += "from guest: %s\n" % rsult_guest
                test.fail(msg)

        error_context.context("Check host name of guest.", logging.info)
        host_name_ga = self.gagent.get_host_name()["host-name"]
        cmd_get_host_name = params["cmd_get_host_name"]
        host_name_guest = session.cmd_output(cmd_get_host_name).strip()
        _result_check(host_name_ga, host_name_guest)

        if params["os_type"] == "linux":
            # this step that set new hostname and
            # check it out just for linux.
            error_context.context("Check host name after setting new host name.",
                                  logging.info)
            cmd_set_host_name = params["cmd_set_host_name"]
            host_name_guest = session.cmd_output(cmd_set_host_name).strip()
            host_name_ga = self.gagent.get_host_name()["host-name"]
            _result_check(host_name_ga, host_name_guest)

        error_context.context("Check timezone of guest.", logging.info)
        timezone_ga = self.gagent.get_timezone()
        timezone_name_ga = timezone_ga["zone"]
        timezone_offset_ga = timezone_ga["offset"]

        logging.info("Check timezone name.")
        cmd_get_timezone_name = params["cmd_get_timezone_name"]
        timezone_name_guest = session.cmd_output(
            cmd_get_timezone_name).strip()
        if params["os_type"] == "windows":
            # there are standard name and daylight name for windows os,
            # both are accepted.
            cmd_dlight_name = params["cmd_get_timezone_dlight_name"]
            timezone_dlight_name_guest = session.cmd_output(
                cmd_dlight_name).strip()
            timezone_name_list = [timezone_name_guest,
                                  timezone_dlight_name_guest]
            if timezone_name_ga not in timezone_name_list:
                msg = "The result is different between qga and guest\n"
                msg += "from qga: %s\n" % timezone_name_ga
                msg += "from guest: %s\n" % timezone_name_list
                test.fail(msg)
        else:
            _result_check(timezone_name_ga, timezone_name_guest)

        logging.info("Check timezone offset.")
        cmd_get_timezone_offset = params["cmd_get_timezone_offset"]
        timezone_offset_guest = session.cmd_output(
            cmd_get_timezone_offset).strip()
        # +08:00
        # (UTC+08:00) Beijing, Chongqing, Hong Kong, Urumqi
        pattern = r"(\S)(\d\d):\d\d"
        timezone_list = re.findall(pattern, timezone_offset_guest, re.I)
        # if it's daylight save time, offset should be 1h early
        if "daylight" in timezone_name_ga.lower():
            offset_seconds = (int(timezone_list[0][1]) - 1) * 3600
        else:
            offset_seconds = int(timezone_list[0][1]) * 3600
        if timezone_list[0][0] == "-":
            timezone_offset_guest_seconds = int(timezone_list[0][0]
                                                + str(offset_seconds))
        else:
            timezone_offset_guest_seconds = int(offset_seconds)
        _result_check(timezone_offset_ga, timezone_offset_guest_seconds)

        error_context.context("Check the current active users number.",
                              logging.info)
        user_qga_list = self.gagent.get_users()
        user_num_qga = len(user_qga_list)
        cmd_get_users = params["cmd_get_users"]
        user_guest = session.cmd_output(cmd_get_users).strip()
        user_guest_list = user_guest.splitlines()

        logging.info("Get all users name in guest.")
        if params["os_type"] == "linux":
            cmd_get_user_name = params["cmd_get_users_name"]
            user_name_guest = session.cmd_output(cmd_get_user_name).strip()
            user_name_list_guest = user_name_guest.splitlines()
        else:
            user_name_list_guest = []
            for user in user_guest_list:
                user = user.strip(' >')
                user_name = user.split()[0]
                user_name_list_guest.append(user_name)
        # get non duplicate user name
        user_num_guest = len(set(user_name_list_guest))

        if user_num_qga != user_num_guest:
            msg = "Currently active users number are different"
            msg += " between qga and guest\n"
            msg += "from qga: %s\n" % len(user_num_qga)
            msg += "from guest: %s\n" % len(user_num_guest)
            test.fail(msg)

        error_context.context("Check the current active users info.",
                              logging.info)
        for user_qga in user_qga_list:
            login_time_qga = user_qga["login-time"]
            user_name_qga = user_qga["user"]

            error_context.context("Check %s user info." % user_name_qga,
                                  logging.info)
            # only have domain key in windows guest
            if params["os_type"] == "windows":
                # username is lowercase letters in windows guest
                user_name = user_name_qga.lower()
                logging.info("Check domain name of %s user." % user_name)
                domain_qga = user_qga["domain"]
                cmd_get_user_domain = params["cmd_get_user_domain"] % user_name
                domain_guest = session.cmd_output(cmd_get_user_domain).strip()
                _result_check(domain_qga, domain_guest)
            else:
                user_name = user_name_qga

            # get this user's info in vm, maybe the same user
            #  loggin many times.
            cmd_get_user = params["cmd_get_user"] % user_name
            records = session.cmd_output(cmd_get_user).strip().splitlines()
            error_context.context("Check active users logging time, if "
                                  "multiple instances of the user are "
                                  "logged in, record the earliest one.",
                                  logging.info)
            first_login = float('inf')
            time_pattern = params["time_pattern"]
            cmd_time_trans = params["cmd_time_trans"]
            for record in records:
                login_time_guest = re.search(time_pattern, record).group(1)
                cmd_time_trans_guest = cmd_time_trans % login_time_guest
                login_time_guest = session.cmd_output(
                    cmd_time_trans_guest).strip()
                first_login = min(first_login, float(login_time_guest))

            delta = abs(float(login_time_qga) - float(first_login))
            if delta > 60:
                msg = "%s login time are different between" % user_name_qga
                msg += " qga and guest\n"
                msg += "from qga: %s\n" % login_time_qga
                msg += "from guest: %s\n" % first_login
                test.fail(msg)

    @error_context.context_aware
    def gagent_check_os_info(self, test, params, env):
        """
        Get operating system info of vm.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        def _result_check(rsult_qga, rsult_guest):
            if rsult_qga.lower() != rsult_guest.lower():
                msg = "The result is different between qga and guest\n"
                msg += "from qga: %s\n" % rsult_qga
                msg += "from guest: %s\n" % rsult_guest
                test.fail(msg)

        session = self._get_session(params, None)
        self._open_session_list.append(session)

        error_context.context("Get os information from qga.", logging.info)

        os_info_qga = self.gagent.get_osinfo()
        os_id_qga = os_info_qga["id"]
        os_name_qga = os_info_qga["name"]
        os_pretty_name_qga = os_info_qga["pretty-name"]
        os_version_qga = os_info_qga["version"]
        os_version_id_qga = os_info_qga["version-id"]
        kernel_version_qga = os_info_qga["kernel-version"]
        kernel_release_qga = os_info_qga["kernel-release"]
        # x86_64 or x86
        machine_type_qga = os_info_qga["machine"]

        cmd_get_full_name = params["cmd_get_full_name"]
        os_name_full_guest = session.cmd_output(cmd_get_full_name).strip()

        error_context.context("Check os basic id and name.", logging.info)
        os_type = params["os_type"]
        os_id = params["os_id"]
        if os_type == "windows":
            os_name = "Microsoft Windows"
        else:
            os_name = re.search(r'(Red Hat.*) release',
                                os_name_full_guest, re.I).group(1)
        _result_check(os_id_qga, os_id)
        _result_check(os_name_qga, os_name)

        error_context.context("Check os pretty name.", logging.info)
        if os_type == "windows":
            os_pretty_name_guest = re.search(
                r'Microsoft (.*)', os_name_full_guest, re.M).group(1)
        else:
            os_pretty_name_guest = os_name_full_guest
            if "release" in os_name_full_guest:
                os_pretty_name_guest = re.sub(r'release ', '',
                                              os_name_full_guest)
        _result_check(os_pretty_name_qga, os_pretty_name_guest)

        error_context.context("Check os version info.", logging.info)
        # 2019, 8.1, 2012 R2, 8
        pattern = r"(\d+(.)?(?(2)(\d+))( R2)?)"
        os_version_id_guest = re.search(pattern,
                                        os_name_full_guest, re.I).group(1)
        if os_type == "windows":
            os_version_guest = re.search(r'(Microsoft.*\d)',
                                         os_name_full_guest, re.I).group(1)
            # 2012 R2
            if "R2" in os_version_id_guest:
                os_version_id_guest = re.sub(r' R2', 'R2',
                                             os_version_id_guest)
        else:
            os_version_guest = re.search(r'release (\d.*)',
                                         os_name_full_guest, re.I).group(1)
            if "Beta" in os_version_guest:
                os_version_guest = re.sub(r'Beta ', '', os_version_guest)

        _result_check(os_version_qga, os_version_guest)
        _result_check(os_version_id_qga, os_version_id_guest)

        error_context.context("Check kernel version and release version.",
                              logging.info)
        cmd_get_kernel_ver = params["cmd_get_kernel_ver"]
        kernel_info_guest = session.cmd_output(cmd_get_kernel_ver).strip()
        if os_type == "windows":
            kernel_g = re.search(r'(\d+\.\d+)\.(\d+)',
                                 kernel_info_guest, re.I)
            kernel_version_guest = kernel_g.group(1)
            kernel_release_guest = kernel_g.group(2)
        else:
            kernel_version_guest = kernel_info_guest
            cmd_get_kernel_rel = params["cmd_get_kernel_rel"]
            kernel_release_guest = session.cmd_output(
                cmd_get_kernel_rel).strip()
        _result_check(kernel_version_qga, kernel_version_guest)
        _result_check(kernel_release_qga, kernel_release_guest)

        error_context.context("Check variant and machine type.", logging.info)
        if self.params.get("os_variant", "") != 'rhel8':
            # for rhel8+ there is no variant info
            # server or client
            variant_qga = os_info_qga["variant"]
            variant_id_qga = os_info_qga["variant-id"]
            variant_guest = "server" \
                if "server" in os_name_full_guest.lower() else "client"
            _result_check(variant_qga, variant_guest)
            _result_check(variant_id_qga, variant_guest)

        cmd_get_machine_type = params["cmd_get_machine_type"]
        machine_type_guest = session.cmd_output(cmd_get_machine_type).strip()
        if os_type == "windows":
            # one of x86, x86_64, arm, ia64
            if "32-bit" in machine_type_guest:
                machine_type_guest = "x86"
            elif "64-bit" in machine_type_guest:
                machine_type_guest = "x86_64"
            else:
                test.error("Only support x86 and x86_64 in this auto test now.")

        _result_check(machine_type_qga, machine_type_guest)

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
        self.gagent_guest_dir = params.get("gagent_guest_dir", "")
        self.qemu_ga_pkg = params.get("qemu_ga_pkg", "")
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
            self._open_session_list.append(session)
            qemu_ga_pkg_path = self.get_qga_pkg_path(self.qemu_ga_pkg, test,
                                                     session, params, self.vm)
            self.gagent_install_cmd = params.get("gagent_install_cmd"
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
                time.sleep(5)

            args = [params.get("gagent_serial_type"), params.get("gagent_name")]
            self.gagent_create(params, self.vm, *args)

    @error_context.context_aware
    def gagent_check_fsfreeze_vss_test(self, test, params, env):
        """
        Test guest agent commands "guest-fsfreeze-freeze/status/thaw"
        for windows guest.

        Test steps:
        1) Check the FS is thawed.
        2) Start writing file test as a background test.
        3) Freeze the FS.
        3) Check the FS is frozen from both guest agent side and guest os side.
        4) Start writing file test as a background test.
        5) Thaw the FS.
        6) Check the FS is thaw from both guest agent side and guest os side.

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment
        """
        @error_context.context_aware
        def background_start(session):
            """
            Before freeze or thaw guest file system, start a background test.
            """
            logging.info("Write time stamp to guest file per second "
                         "as a background job.")
            fswrite_cmd = utils_misc.set_winutils_letter(
                session, self.params["gagent_fs_test_cmd"])

            session.cmd(fswrite_cmd, timeout=360)

        @error_context.context_aware
        def result_check(flag, write_timeout, session):
            """
            Check if freeze or thaw guest file system works.

            :param flag: frozen or thaw
            :param write_timeout: timeout of writing to guest file
            """
            time.sleep(write_timeout)
            k_cmd = "wmic process where \"name='python.exe' and " \
                    "CommandLine Like '%fsfreeze%'\" call terminate"
            s, o = session.cmd_status_output(k_cmd)
            if s:
                self.test.error("Command '%s' failed, status: %s,"
                                " output: %s" % (k_cmd, s, o))

            error_context.context("Check guest FS status.", logging.info)
            # init fs status to 'thaw'
            fs_status = "thaw"
            file_name = "/tmp/fsfreeze_%s.txt" % flag
            process.system("rm -rf %s" % file_name)
            self.vm.copy_files_from("C:\\fsfreeze.txt", file_name)
            with open(file_name, 'r') as f:
                list_time = f.readlines()

            for i in list(range(0, len(list_time))):
                list_time[i] = list_time[i].strip()

            for i in list(range(1, len(list_time))):
                num_d = float(list_time[i]) - float(list_time[i - 1])
                if num_d > 8:
                    logging.info("Time stamp is not continuous,"
                                 " so the FS is frozen.")
                    fs_status = "frozen"
                    break
            if not fs_status == flag:
                self.test.fail("FS is not %s, it's %s." % (flag, fs_status))

        error_context.context("Check guest agent command "
                              "'guest-fsfreeze-freeze/thaw'",
                              logging.info)
        session = self._get_session(self.params, None)
        self._open_session_list.append(session)

        # make write time longer than freeze timeout
        write_timeout = int(params["freeze_timeout"]) + 10
        try:
            expect_status = self.gagent.FSFREEZE_STATUS_THAWED
            self.gagent.verify_fsfreeze_status(expect_status)
        except guest_agent.VAgentFreezeStatusError:
            # Thaw guest FS if the fs status is incorrect.
            self.gagent.fsthaw(check_status=False)

        error_context.context("Before freeze/thaw the FS, run the background "
                              "job.", logging.info)
        background_start(session)
        error_context.context("Freeze the FS.", logging.info)
        self.gagent.fsfreeze()
        try:
            error_context.context("Waiting %s, then finish writing the time "
                                  "stamp in guest file." % write_timeout)
            result_check("frozen", write_timeout, session)
            # Next, thaw guest fs.
            error_context.context("Before freeze/thaw the FS, run the background "
                                  "job.", logging.info)
            background_start(session)
            error_context.context("Thaw the FS.", logging.info)
            try:
                self.gagent.fsthaw()
            except guest_agent.VAgentCmdError as detail:
                if re.search("fsfreeze is limited up to 10 seconds", str(detail)):
                    logging.info("FS is thaw as it's limited up to 10 seconds.")
                else:
                    test.fail("guest-fsfreeze-thaw cmd failed with:"
                              "('%s')" % str(detail))
        except Exception:
            # Thaw fs finally, avoid problem in following cases.
            try:
                self.gagent.fsthaw(check_status=False)
            except Exception as detail:
                # Ignore exception for this thaw action.
                logging.warn("Finally failed to thaw guest fs,"
                             " detail: '%s'", detail)
            raise
        error_context.context("Waiting %s, then finish writing the time "
                              "stamp in guest file." % write_timeout)
        result_check("thaw", write_timeout, session)

    @error_context.context_aware
    def gagent_check_fstrim(self, test, params, env):
        """
        Execute "guest-fstrim" command via guest agent.

        Steps:
        1) boot up guest with scsi backend device
        2) init and format the data disk
        3) get the original blocks of data disk
        4) create fragment in data disk
        5) check the used blocks
        6) execute fstrim cmd via guest agent
        7) check if the used blocks is decreased

        :param test: kvm test object
        :param params: Dictionary with the test parameters
        :param env: Dictionary with test environment.
        """
        def get_blocks():
            """
            Get the used blocks of data disk.
            :return: the used blocks
            """
            blocks = process.system_output("stat -t %s" % image_filename_stg)
            return blocks.strip().split()[2]

        session = self._get_session(params, None)
        self._open_session_list.append(session)

        error_context.context("Format data disk.", logging.info)
        image_size_stg = params["image_size_stg"]
        disk_index = utils_misc.wait_for(
            lambda: utils_disk.get_windows_disks_index(session,
                                                       image_size_stg), 120)
        if not disk_index:
            test.error("Didn't get windows disk index.")
        logging.info("Clear readonly of disk and online it in windows guest.")
        if not utils_disk.update_windows_disk_attributes(session, disk_index):
            test.error("Failed to update windows disk attributes.")
        mnt_point = utils_disk.configure_empty_disk(
            session, disk_index[0], image_size_stg, "windows",
            labeltype="msdos")

        error_context.context("Check the original blocks of data disk.",
                              logging.info)
        image_params_stg = params.object_params("stg")
        image_filename_stg = storage.get_image_filename(
            image_params_stg, data_dir.get_data_dir())
        blocks_init = get_blocks()
        logging.info("The blocks original is %s" % blocks_init)

        error_context.context("Create fragment in data disk.", logging.info)
        guest_dir = r"%s:" % mnt_point[0]
        data_file = os.path.join(guest_dir,
                                 "qga_fstrim%s" %
                                 utils_misc.generate_random_string(5))
        for i in range(5):
            count = 1000 * (i + 1)
            logging.info("Create %sM file in guest." % count)
            cmd = "dd if=/dev/random of=%s bs=1M count=%d" % (data_file, count)
            session.cmd(cmd, timeout=600)
            delete_file_cmd = "%s %s" % (params["delete_file_cmd"],
                                         data_file.replace("/", "\\"))
            logging.info("Delete the guest file created just now.")
            session.cmd(delete_file_cmd)

        error_context.context("Check blocks of data disk before fstrim.",
                              logging.info)
        blocks_before_fstrim = get_blocks()
        if int(blocks_init) >= int(blocks_before_fstrim):
            msg = "Fragment created failed in data disk\n"
            msg += "the blocks original is %s\n" % blocks_init
            msg += "the blocks before fstrim is %s." % blocks_before_fstrim
            test.error("msg")

        error_context.context("Execute the guest-fstrim cmd via qga.",
                              logging.info)
        self.gagent.fstrim()

        error_context.context("Check blocks of data disk after fstrim.",
                              logging.info)
        blocks_after_fstrim = get_blocks()

        if int(blocks_after_fstrim) >= int(blocks_before_fstrim):
            msg = "Fstrim failed\n"
            msg += "the blocks before fstrim is %s\n" % blocks_before_fstrim
            msg += "the blocks after fstrim is %s." % blocks_after_fstrim
            test.fail(msg)


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
