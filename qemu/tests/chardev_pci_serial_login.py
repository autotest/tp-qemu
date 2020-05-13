import aexpect

from virttest import error_context, env_process
from virttest import utils_misc, remote


@error_context.context_aware
def run(test, params, env):
    """
    Verify the login function of pci-serial (RHEL and x86 only):
    1) Start guest with pci-serial with backend unix_socket
    2) append console=ttyS0 to guest kernel config
    3) append /dev/ttyS0 to /etc/security
    4) reboot guest
    5) nc host/path for unix and tcp backend.
    6) login to guest and move files, restart network
    7) repeat step 1 to 6 with pty, tcp backend
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    serial_id = params.objects('serials')[-1]
    prompt = "[#$]"
    params['start_vm'] = 'yes'
    for backend in ['tcp_socket', 'unix_socket']:
        params['chardev_backend_%s' % serial_id] = backend
        env_process.preprocess_vm(test, params, env, params['main_vm'])
        vm = env.get_vm(params["main_vm"])
        vm.verify_alive()
        serial_device = vm.devices.get(serial_id)
        chardev_qid = serial_device.get_param("chardev")
        chardev_device = vm.devices.get_by_qid(chardev_qid)[0]
        if backend == 'tcp_socket':
            nc_command = ('nc %s %s' % (chardev_device.params['host'], chardev_device.params['port']))
        elif backend == 'unix_socket':
            nc_command = ('nc -U %s' % chardev_device.params['path'])
        session = aexpect.ShellSession(nc_command, auto_close=False, output_func=utils_misc.log_line, output_params=('/tmp/test.log',), prompt=prompt)
        session.set_linesep('\n')
        session.sendline()
        remote.handle_prompts(session, 'root', 'kvmautotest', prompt, 180)
        assert session.cmd('lspci | grep "PCI 16550A"') is not None, 'Cannot find PCI device'
        session.cmd('touch file.txt')
        session.cmd('mkdir -p tmp')
        session.cmd('command cp file.txt ./tmp/test.txt')
