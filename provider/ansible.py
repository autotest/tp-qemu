import os
import logging

from aexpect.client import Expect

from avocado.utils import path
from avocado.utils import process
from avocado.utils import software_manager
from avocado.utils.wait import wait_for


class SyntaxCheckError(Exception):
    def __init__(self, cmd, output):
        self.cmd = cmd
        self.output = output

    def __str__(self):
        return ('The ansible-playbook command "{}" cannot pass syntax check: '
                '{}'.format(self.cmd, self.output))


class ExecutorTimeoutError(Exception):
    pass


def find_playbook_program():
    """ Return to the path of ansible-playbook. """
    try:
        path.find_command('ansible-playbook')
    except path.CmdNotFoundError:
        sm = software_manager.SoftwareManager()
        sm.install('ansible')
    return path.find_command('ansible-playbook')


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
        self.program = find_playbook_program()
        self.inventory = inventory
        self.site_yml = site_yml
        self.remote_user = remote_user
        self.callback_plugin = callback_plugin
        super(PlaybookExecutor, self).__init__(self._generate_cmd(extra_vars,
                                                                  addl_opts))
        logging.info("Command of ansible playbook: '%s'", self.command)

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
        logging.info('ansible-playbook execution is completed.')

    def store_playbook_log(self, log_dir, filename):
        """
        Save the ansible-playbook outputs to a specified file.

        :param log_dir: Path of the log directory.
        :param filename: the log file name.
        """
        with open(os.path.join(log_dir, filename), 'w') as log_file:
            log_file.write(self.get_output())
            log_file.flush()
