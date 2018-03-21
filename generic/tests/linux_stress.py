import time
import logging
import aexpect

from avocado.utils import download

from virttest import data_dir
from virttest import utils_misc
from virttest import error_context


class Stress(object):
    """
    Stress utility for linux guest
    """

    def __init__(self, params, vm):
        """
        Initialize StressTest object

        :param params: Dictionary with the test parameters
        :param vm: Object qemu_vm.VM, the guest need stress
        """
        self.params = params
        self.dst_path = "/home"
        self.tarball_name = 'stress-1.0.4'
        self.downloaded = False
        self.vm = vm

    @error_context.context_aware
    def download_and_uncompress_stress(self):
        """
        Download and uncompress the stress tarball
        """
        download_url = self.params.get('download_url',
                                       'http://people.seas.harvard.edu/'
                                       '~apw/stress/stress-1.0.4.tar.gz')

        tarball_path = '%s/%s.tar.gz' % (data_dir.get_data_dir(),
                                         self.tarball_name)
        pkg_md5 = self.params.get('pkg_md5', '890a4236dd1656792f3ef9a190cf99ef')
        error_context.context('Download stress tarball', logging.info)
        tarball_path = download.get_file(
            download_url, tarball_path, hash_expected=pkg_md5)

        error_context.context('Copy stress tarball to guest', logging.info)
        self.vm.copy_files_to(tarball_path, self.dst_path)
        tarball_path = '%s/%s.tar.gz' % (self.dst_path, self.tarball_name)

        uncompress_cmd = self.params.get('uncompress_cmd', 'tar xvfz %s -C %s')
        uncompress_cmd = uncompress_cmd % (tarball_path, self.dst_path)
        error_context.context('Uncompress the stress tarball', logging.info)
        session = self.vm.wait_for_login()
        if session.cmd_status(uncompress_cmd) == 0:
            session.cmd_output_safe("rm -f %s" % tarball_path)
        session.close()
        self.dst_path = '%s/%s' % (self.dst_path, self.tarball_name)
        self.downloaded = True

    @error_context.context_aware
    def install(self):
        """
        To download, abstract, build and install the stress

        :return: True if installation success, otherwise False
        """
        if self.check_installed():
            error_context.context('stress has already been installed.')
            return True
        else:
            error_context.context('stress has not been installed, '
                                  'download and install...')
            self.download_and_uncompress_stress()
            session = self.vm.wait_for_login()
            session.cmd_output_safe('cd %s' % self.dst_path)
            make_cmd = self.params.get(
                'make_cmd', './configure && make && make install')
            error_context.context('make and install the stress app', logging.info)
            session.cmd_output_safe(make_cmd)
            session.close()
            return self.check_installed()

    def check_installed(self):
        """
        Check if stress is installed

        :return: True if it is installed, otherwise False
        """
        check_installed_cmd = self.params.get(
            'check_installed_cmd', 'stress --help')
        session = self.vm.wait_for_login()
        installed = session.cmd_status(check_installed_cmd) == 0
        session.close()
        return installed

    @error_context.context_aware
    def uninstall(self):
        """
        Uninstall stress application, and clean the source files

        :return: True if uninstall success, otherwise False
        """
        session = self.vm.wait_for_login()
        if session.cmd_status('rpm -e stress') == 0:
            session.close()
            return True

        if not self.downloaded:
            self.download_and_uncompress_stress()
        session.cmd_output_safe('cd %s' % self.dst_path)

        uninstall_cmd = './configure && make uninstall'
        error_context.context('Uninstall stress', logging.info)
        status, output = session.cmd_status_output(uninstall_cmd)
        if status != 0:
            error_context.context('Uninstall stress failed with '
                                  'error: %s' % output, logging.error)
            session.close()
            return False

        error_context.context('Uninstall stress success, now '
                              'remove the source files', logging.info)
        rm_cmd = 'cd && rm -rf %s' % self.dst_path
        removed = session.cmd_status(rm_cmd) == 0
        session.close()
        return removed

    def launch_stress(self):
        """
        Launch stress test, and check if the process exist,
        raise test error if not

        :return True if stress process alive, otherwise False
        """
        session = self.vm.wait_for_login()
        options = self.params.get('stress_options',
                                  '--cpu 2 --io 1 --vm 1 --vm-bytes 128M')
        try:
            session.cmd_output_safe('stress %s &' % options)
        # The background process sometimes does not return to
        # terminate, if timeout, send a blank line afterward
        except aexpect.ShellTimeoutError:
            session.cmd_output_safe('')
        session.close()
        return self.check_alive()

    @error_context.context_aware
    def check_alive(self, timeout=5):
        """
        Check if the stress process alive or not

        :param timeout: timeout to verify the process alive
        :return: True if stress process alive, otherwise False
        """
        session = self.vm.wait_for_login()
        check_alive_cmd = self.params.get('check_alive_cmd', 'pgrep stress')
        error_context.context('Check if the stress process alive', logging.info)
        time.sleep(timeout)
        alive = utils_misc.wait_for(lambda:
                                    session.cmd_output_safe(check_alive_cmd),
                                    timeout=timeout)
        session.close()
        return alive

    @error_context.context_aware
    def stop_stress(self):
        """
        Stop the stress process, and verify if it is still alive
        """
        session = self.vm.wait_for_login()
        if self.check_alive():
            stop_command = self.params.get('stop_cmd', 'killall -g stress')
            session.cmd_output_safe(stop_command)
        # Log it if stop stress failed, it will not fail the test
        # case since stop stress failure is not really harmful
        if self.check_alive():
            error_context.context('stop stress failed', logging.info)
        session.close()


def run(test, params, env):
    """
    General stress test for linux:
       1). Install stress if need
       2). Start stress process
       3). If no stress_time defined, keep stress until test_timeout;
       otherwise execute below steps after sleeping stress_time long
       4). Stop stress process
       5). Uninstall stress
       6). Verify guest kernel crash

    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    vm = env.get_vm(params['main_vm'])
    vm.verify_alive()
    stress = Stress(params, vm)
    if not stress.install():
        test.fail("stress app installation failed")
    if not stress.launch_stress():
        test.fail("launch stress app failed")
    stress_time = int(params.get('stress_time'))
    if stress_time:
        time.sleep(stress_time)
        stress.stop_stress()
        stress.uninstall()
        vm.verify_kernel_crash()
