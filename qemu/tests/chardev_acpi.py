from avocado.utils import process
from virttest import env_process, error_context


@error_context.context_aware
def run(test, params, env):
    """
    acpi description of serial and parallel ports incorrect
    with -chardev/-device:
    1) Check device resources(io port and irq) on host
    2) Boot guest A with isa-serial with tty chardev backend
    3) Check device resources inside guest A
    4) Boot guest B with -serial /dev/ttyS0
    5) Check device resources inside guest B
    6) Check if the result are same for host, A and B.
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    outputs = []
    check_cmd = params["check_cmd"]
    host_output = process.getoutput(check_cmd)[:35]
    outputs.append(host_output)
    for x in range(2):
        if x >= 1:
            params["serials"] = " ".join(params["serials"].split()[:-1])
            params["extra_params"] = (
                params.get("extra_params", "") + " -serial /dev/ttyS0"
            )
            env_process.preprocess(test, params, env)
        vm = env.get_vm(params["main_vm"])
        session = vm.wait_for_login()
        vm_output = session.cmd_status_output(check_cmd)[1][:35]
        outputs.append(vm_output)
        vm.destroy()
    assert outputs.count(outputs[0]) == len(
        outputs
    ), "Host: {} and VM 1: {} and VM 2: {} are not the same".format(
        outputs[0], outputs[1], outputs[2]
    )
