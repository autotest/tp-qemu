import os
import logging

from aexpect.client import Expect

from avocado.utils import path
from avocado.utils import process
from avocado.utils.wait import wait_for
from avocado.utils.software_manager.backends.yum import YumBackend

from virttest import utils_package

LOG_JOB = logging.getLogger('avocado.test')


class SyntaxCheckError(Exception):
    def __init__(self, cmd, output):
        self.cmd = cmd
        self.output = output

    def __str__(self):
        return ('The ansible-playbook command "{}" cannot pass syntax check: '
                '{}'.format(self.cmd, self.output))


class ExecutorTimeoutError(Exception):
    pass


class PlaybookExecutor(Expect):
    def __init__(self, inventory, site_yml, remote_user=None, extra_vars=None,
                 callback_plugin=None, addl_opts=None):
        """
        The wrapper of Ansible-playbook.

        :param inventory: Specify inventory host path or comma separated list.
        :param site_yml: Path of the top level playbook.
        :param remote_user: Connect as this user.
        :param extra_vars: Set additional variables.
        :param callback_plugin: The plugin of the main manager of console output.
        :param addl_opts: Other ansible-playbook common options.
        """
        self.program = path.find_command('ansible-playbook')
        self.inventory = inventory
        self.site_yml = site_yml
        self.remote_user = remote_user
        self.callback_plugin = callback_plugin
        super(PlaybookExecutor, self).__init__(self._generate_cmd(extra_vars,
                                                                  addl_opts))
        LOG_JOB.info("Command of ansible playbook: '%s'", self.command)

    def _generate_cmd(self, extra_vars=None, addl_opts=None):
        """
        Generate the ansible-playbook command line to be used.

        :param extra_vars: et additional variables.
        :param addl_opts: Other ansible-playbook common options.
        :return: The generated ansible-playbook command line.
        """
        playbook_cmd_options = []
        if self.callback_plugin:
            playbook_cmd_options = [
                'ANSIBLE_STDOUT_CALLBACK={}'.format(self.callback_plugin)]
        playbook_cmd_options.extend([self.program,
                                     self.site_yml,
                                     '-i {}'.format(self.inventory)])
        not self.remote_user or playbook_cmd_options.append(
            '-u {}'.format(self.remote_user))
        not extra_vars or playbook_cmd_options.append(
            "-e '{}'".format(extra_vars))
        not addl_opts or playbook_cmd_options.append(addl_opts)
        playbook_cmd = r' '.join(playbook_cmd_options)
        self._syntax_check(playbook_cmd)
        return playbook_cmd

    @staticmethod
    def _syntax_check(cmd):
        """
        perform a syntax check on the playbook, but do not execute it.

        :param cmd: The generated ansible-playbook command line.
        """
        try:
            process.run(cmd + ' --syntax-check', verbose=False, shell=True)
        except process.CmdError as err:
            raise SyntaxCheckError(cmd, err.result.stdout_text)

    def wait_for_completed(self, timeout, step_time=10):
        """
        Waiting for ansible-playbook process to complete execution and exit

        :param timeout: Timeout in seconds.
        :param step_time: Time to sleep between attempts in seconds.
        """
        if not wait_for(lambda: not self.is_alive(), timeout, step=step_time,
                        text='Waiting for the ansible-playbook process to '
                             'complete...'):
            self.kill()
            raise ExecutorTimeoutError('ansible-playbook cannot complete all '
                                       'tasks within the expected time.')
        LOG_JOB.info('ansible-playbook execution is completed.')

    def store_playbook_log(self, log_dir, filename):
        """
        Save the ansible-playbook outputs to a specified file.

        :param log_dir: Path of the log directory.
        :param filename: the log file name.
        """
        with open(os.path.join(log_dir, filename), 'w') as log_file:
            log_file.write(self.get_output())
            log_file.flush()


def check_ansible_playbook(params):
    """
    check if ansible-playbook exists or not.

    :param params: Dictionary with the test parameters.
    :return: True if full ansible version is installed, else False.
    """

    def _pip_binary():
        """
        Define pip binary
        """
        for binary in ['pip', 'pip3', 'pip2']:
            if process.system("which %s" % binary, ignore_status=True) == 0:
                return binary
        LOG_JOB.error("Failed to get available pip binary")
        return False

    def python_install():
        """
        Install python ansible.
        """
        install_cmd = '%s install ansible' % pip_bin    # pylint: disable=E0606
        status, output = process.getstatusoutput(install_cmd, verbose=True)
        if status != 0:
            LOG_JOB.error("Install python ansible failed as: %s", output)
            return False
        return True

    def distro_install(packages="ansible"):
        """
        Install ansible from the distro
        """
        # Provide custom dnf repo containing ansible
        if params.get("ansible_repo"):
            repo_options = {
                "priority": "1",
                "gpgcheck": "0",
                "skip_if_unavailable": "1"
            }
            yum_backend = YumBackend()
            if yum_backend.add_repo(params["ansible_repo"], **repo_options):
                LOG_JOB.info(f"Ansible repo was added: {params['ansible_repo']}")
            else:
                LOG_JOB.error("Ansible repo was required, but failed to be added.")
                return False
        install_status = utils_package.package_install(packages)
        if not install_status:
            LOG_JOB.error(f"Failed to install {packages}.")
        # Remove custom dnf repo when it is no longer used
        if params.get("ansible_repo"):
            yum_backend.remove_repo(params["ansible_repo"])
        return install_status

    policy_map = {"distro_install": distro_install,
                  "python_install": python_install}

    ansible_install_policy = params.get('ansible_install_policy')
    if ansible_install_policy:
        if ansible_install_policy not in policy_map:
            LOG_JOB.error(f"No valid install policy: {ansible_install_policy}.")
            return False
    package_list = params.get_list("package_list", 'sshpass')
    try:
        check_cmd = params.get("ansible_check_cmd")
        if ansible_install_policy == 'python_install':
            global pip_bin
            pip_bin = _pip_binary()
            check_cmd = rf"{pip_bin} freeze | grep -v ansible-core | grep -q ansible="
        elif ansible_install_policy == 'distro_install':
            package_list.insert(0, 'ansible')
        if check_cmd:
            LOG_JOB.debug(f"Is full ansible version installed: '{check_cmd}'")
            process.run(check_cmd, verbose=False, shell=True)
        else:
            path.find_command('ansible-playbook')
    except (path.CmdNotFoundError, process.CmdError):
        # If except block is reached and no ansible install policy
        # is defined it is not possible to install ansible at all
        if not ansible_install_policy:
            return False
        if not policy_map[ansible_install_policy]():
            return False
    # Install ansible depended packages that can't be installed
    # by pip (or are not a dependency) when installing ansible
    if not policy_map['distro_install'](package_list):
        return False
    # If ansible and dependents packages are installed correctly
    return True
