from virttest import error_context
from virttest import env_process


@error_context.context_aware
def run(test, params, env):
    """
    acpi description of serial and parallel ports incorrect
    with -chardev/-device:
    1) Boot guest A with isa-serial with tty chardev backend
    2) Enter into guest A
        udevadm info --query path --name /dev/ttyS0
        !! --attribute-walk | grep looking
    3) Boot guest B with -serial /dev/ttyS0
    4) repeat step 2 for guest B
    5) Check if the result are same for A and B.
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    outputs = []
    guest_cmd = params['guest_cmd']
    for x in range(2):
        if x >= 1:
            params['serials'] = " ".join(params['serials'].split()[:-1])
            params['extra_params'] = params.get('extra_params', '') + ' -serial /dev/ttyS0'
            env_process.preprocess(test, params, env)
        vm = env.get_vm(params["main_vm"])
        session = vm.wait_for_login()
        vm_output1 = session.cmd_status_output(guest_cmd)
        # !! cannot be used because of echo $?
        vm_output2 = session.cmd_status_output("{} --attribute-walk | grep looking".format(guest_cmd))
        outputs.append([vm_output1, vm_output2])
        vm.destroy()
    assert outputs.count(outputs[0]) == len(outputs), 'output 1: {} and output 2: {} are not the same'.format(outputs[0], outputs[1])
