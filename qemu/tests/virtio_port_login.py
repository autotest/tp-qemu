"""
Collection of virtio_console and virtio_serialport tests.

:copyright: 2010-2012 Red Hat Inc.
"""
import logging

import aexpect

from autotest.client.shared import error

from virttest import utils_misc
from virttest import remote
from virttest import utils_virtio_port


class ConsoleLoginTest(utils_virtio_port.VirtioPortTest):

    __sessions__ = []

    def __init__(self, test, env, params):
        super(ConsoleLoginTest, self).__init__(test, env, params)
        self.vm = self.get_vm_with_ports(no_consoles=1, no_serialports=1)

    @error.context_aware
    def pre_step(self):
        error.context("Config guest and reboot it", logging.info)
        pre_cmd = self.params.get("pre_cmd") + self.params.get("pre_cmd_extra")
        session = self.vm.wait_for_login(timeout=360)
        session.cmd(pre_cmd, timeout=240)
        session = self.vm.reboot(session=session, timeout=900, serial=False)
        self.__sessions__.append(session)

    @error.context_aware
    def virtio_console_login(self, port='vc1'):
        error.context("Login guest via '%s'" % port, logging.info)
        session = self.vm.wait_for_serial_login(timeout=180, virtio=port)
        self.__sessions__.append(session)
        return session

    def console_login(self, port='vc1'):
        return self.virtio_console_login(port=port)

    @error.context_aware
    def virtio_serial_login(self, port='vs1'):
        error.context("Try to login guest via '%s'" % port, logging.info)
        username = self.params.get("username")
        password = self.params.get("password")
        prompt = self.params.get("shell_prompt", "[\#\$]")
        linesep = eval("'%s'" % self.params.get("shell_linesep", r"\n"))
        for vport in self.get_virtio_ports(self.vm)[1]:
            if vport.name == port:
                break
            vport = None
        if not vport:
            raise error.TestError("Not virtio serial port '%s' found" % port)

        logfile = "serial-%s-%s.log" % (vport.name, self.vm.name)
        socat_cmd = "nc -U %s" % vport.hostfile
        session = aexpect.ShellSession(socat_cmd, auto_close=False,
                                       output_func=utils_misc.log_line,
                                       output_params=(logfile,),
                                       prompt=prompt)
        session.set_linesep(linesep)
        session.sendline()
        self.__sessions__.append(session)
        try:
            remote.handle_prompts(session, username, password, prompt, 180)
            raise error.TestFail("virtio serial '%s' should no " % port +
                                 "channel to login")
        except remote.LoginTimeoutError:
            self.__sessions__.append(session)
            logging.info("Can't login via %s" % port)
        return session

    def serial_login(self, port="vc1"):
        return self.virtio_serial_login(port=port)

    @error.context_aware
    def cleanup(self):
        error.context("Close open connection and destroy vm", logging.info)
        for session in self.__sessions__:
            if session:
                session.close()
            self.__sessions__.remove(session)
        super(ConsoleLoginTest, self).cleanup(vm=self.vm)


def run(test, params, env):
    """
    KVM virtio_console test

    Basic function test to check virtio console login function.
    :param test: kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment
    """
    login_console = params.get("login_console", "vc1")
    console_params = params.object_params(login_console)
    console_test = ConsoleLoginTest(test, env, params)
    try:
        console_test.pre_step()
        port_type = console_params.get("virtio_port_type")
        login_func = "%s_login" % port_type
        logging.info("Login function: %s" % login_func)
        session = getattr(console_test, login_func)(login_console)
        if "serial" not in port_type:
            for cmd in params.get("shell_cmd_list", "dir").split(","):
                logging.info("sending command: %s" % cmd)
                output = session.cmd_output(cmd, timeout=240)
                logging.info("output:%s" % output)
        clean_cmd = params["clean_cmd"]
        session.cmd(clean_cmd, timeout=180)
        session.close()
    except Exception:
        console_test.cleanup()
        raise
