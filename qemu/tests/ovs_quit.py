from avocado.utils import process
from avocado.utils import path as utils_path

from virttest import data_dir
from virttest import env_process
from virttest import error_context
from virttest import virt_vm


@error_context.context_aware
def run(test, params, env):
    """
    Test tap device deleted after vm quit with error

    1) Boot a guest with invaild params.
    1) Check qemu-kvm quit with error.
    2) Check vm tap device delete from ovs bridge.

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_ovs_ports(ovs):
        cmd = "ovs-vsctl list-ports %s" % ovs
        return set(process.system_output(cmd).splitlines())

    utils_path.find_command("ovs-vsctl")
    netdst = params.get("netdst")
    if netdst not in process.system_output("ovs-vsctl list-br"):
        test.cancel("%s isn't an openvswith bridge" % netdst)

    deps_dir = data_dir.get_deps_dir("ovs")

    params["qemu_command_prefix"] = "export SHELL=/usr/bin/bash;"
    params["start_vm"] = "yes"
    params["nettype"] = "bridge"
    params["nic_model"] = "virtio-pci"

    try:
        ports = get_ovs_ports(netdst)
        env_process.preprocess_vm(test, params, env, params["main_vm"])
        env.get_vm(params["main_vm"])
    except (virt_vm.VMCreateError, virt_vm.VMStartError) as err_msg:
        match_error = "Parameter 'driver' expects"
        output = getattr(err_msg, 'reason', getattr(err_msg, 'output', ''))
        if match_error in output:
            ports = get_ovs_ports(netdst) - ports
            if ports:
                for p in ports:
                    process.system("ovs-vsctl del-if %s %s" % (netdst, p))
                test.fail("%s not delete after qemu quit." % ports)
        else:
            test.fail("VM create failed with not expected error: %s!" % output)
    else:
        env.get_vm(params["main_vm"]).graceful_shutdown()
        process.system_output("ovs-vsctl list-br")
        test.fail("Qemu should quit with error")
