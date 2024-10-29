import logging
import re
import time

from virttest import utils_package

LOG_JOB = logging.getLogger("avocado.test")


class IpuTest(object):
    """
    Class for in_place_upgrade test in the vm
    """

    def __init__(self, test, params):
        """
        Init the default values of in_place_upgrade object.

        :param params: A dict containing VM preprocessing parameters.
        :param env: The environment (a dict-like object).
        """
        self.session = None
        self.test = test
        self.params = params

    def run_guest_cmd(self, cmd, check_status=True, timeout=1200):
        """
        Run command in guest

        :param cmd: A command needed to run
        :param check_status: If true, check the status after running the cmd
        :return: The output after running the cmd
        """
        status, output = self.session.cmd_status_output(cmd, timeout=timeout)
        if check_status and status != 0:
            self.test.fail("Execute command %s failed, output: %s" % (cmd, output))
        return output.strip()

    def upgrade_process(self, cmd, timeout=6000):
        """
        Fix known issues before doing in place upgradet

        :param cmd: A command needed to run
        """
        self.session.cmd(cmd, timeout=timeout)

    def yum_update_no_rhsm(self, test, old_custom):
        """
        do yum update in the vm
        """
        try:
            pkgs = self.params.get("depends_pkgs").split()
            if not utils_package.package_install(pkgs, self.session):
                test.cancel("Install dependency packages failed")
            self.session.cmd(old_custom)
            dis_content = self.params.get("disable_content")
            self.session.cmd(dis_content, timeout=300)
            ena_content = self.params.get("enable_content")
            self.session.cmd(ena_content, timeout=300)
            self.session.cmd(self.params.get("stop_yum_update"))
            self.session.cmd(self.params.get("check_repo_list"))
            update_vm = self.params.get("yum_update")
            self.session.cmd(update_vm, timeout=3000)
        except Exception as error:
            test.fail("Failed to do yum update in the vm : %s" % str(error))

    def rhsm(self, test):
        """
        register your system to server
        """
        try:
            self.session.cmd_status_output(self.params.get("configure_rhsm"))
            subscribe_register = self.params.get("subscribe_register_rhsm")
            self.session.cmd(subscribe_register, timeout=600)
            get_poolid = self.params.get("get_pool_id")
            s, output = self.session.cmd_status_output(get_poolid, timeout=600)
            attach_pool = self.params.get("attach_pool") + output
            if output == "":
                test.cancel("No pool is found, please check the server")
            self.session.cmd(attach_pool, timeout=600)
            ena_content = self.params.get("enable_content")
            self.session.cmd(ena_content, timeout=3000)
            self.session.cmd(self.params.get("stop_yum_update"))
            self.session.cmd(self.params.get("check_repo_list"), timeout=300)
            o = self.session.cmd_output(self.params.get("check_rhel_ver"), timeout=60)
            set_ver = o[:1] + "." + o[1:]
            set_ver_com = self.params.get("set_release") + set_ver
            self.session.cmd(set_ver_com, timeout=300)
            update_vm = self.params.get("yum_update")
            self.session.cmd(update_vm, timeout=6000)
        except Exception as error:
            test.fail("Failed to register rhsm : %s" % str(error))

    def create_ipuser(self, test):
        """
        Create an user since disabling root login
        """
        try:
            add_ipuser = self.params.get("add_ipuser")
            add_wheel_ipuser = self.params.get("add_wheel_ipuser")
            add_passwd_ipuser = self.params.get("add_passwd_ipuser")
            no_passwd_for_sudo = self.params.get("no_passwd_for_sudo")
            self.session.cmd(add_ipuser)
            self.session.cmd(add_wheel_ipuser)
            self.session.cmd(add_passwd_ipuser)
            self.session.cmd(no_passwd_for_sudo)
        except Exception as error:
            test.fail("Failed to create ipuser : %s" % str(error))

    def pre_upgrade_whitelist(self, test):
        """
        Fix known issues after executing pre-upgrade
        """
        try:
            # Leapp and grubby's version
            le = self.session.cmd_output("rpm -qa|grep ^leapp")
            test.log.info("leapp version: %s", str(le))
            gr = self.session.cmd_output("rpm -qa|grep grubby")
            test.log.info("grubby version: %s", str(gr))
            # Firewalld Configuration AllowZoneDrifting Is Unsupported
            self.session.cmd(self.params.get("fix_firewalld"))
            # Possible problems with remote login using root account
            self.session.cmd(self.params.get("fix_permit"))
            # New kernel is not used
            erase_old_kernel = self.params.get("clean_up_old_kernel")
            s, output = self.session.cmd_status_output(erase_old_kernel, timeout=1200)
            error_info = self.params.get("error_info")
            if re.search(error_info, output):
                pass
            if self.params.get("rmmod_module"):
                self.session.cmd(self.params.get("rmmod_module"))
        except Exception as error:
            test.fail("Failed to fix issues in advance: %s" % str(error))

    def post_upgrade_check(self, test, post_release):
        """
        Check the new system is expected
        """
        try:
            release = self.params.get("release_check")
            status, output_release = self.session.cmd_status_output(release)
            if not re.search(post_release, output_release):
                test.fail(
                    "Post_release: %s, expected result: %s"
                    % (post_release, output_release)
                )
            new_kernel = self.params.get("new_kernel_ver")
            check_kernel = self.params.get("check_kernel")
            s, actual_new_kernel = self.session.cmd_status_output(check_kernel)
            if not re.search(new_kernel, actual_new_kernel):
                test.fail(
                    "kernel is not right, expected is %s and new is %s"
                    % (new_kernel, actual_new_kernel)
                )
        except Exception as error:
            test.fail("Post upgrade checking failed : %s" % str(error))

    def post_upgrade_restore(self, test):
        """
        Restore settings in the vm
        """
        try:
            timeout = 1200
            endtime = time.time() + timeout
            re_permit = self.params.get("restore_permit")
            check_file = self.params.get("check_file")
            while time.time() < endtime:
                s, o = self.session.cmd_status_output(check_file)
                if re.search("answerfile", o):
                    s, o = self.session.cmd_status_output(re_permit)
                    if s:
                        test.fail("Failed to restore permit: %s" % o)
                    re_sshd_service = self.params.get("restart_sshd")
                    break
                else:
                    test.fail("upgrade is in proress, please add waiting time")
            s, o = self.session.cmd_status_output(re_sshd_service)
            if s != 0:
                test.fail("Failed to restart sshd: %s" % o)
        except Exception as error:
            test.fail("Failed to restore permit: %s" % str(error))
