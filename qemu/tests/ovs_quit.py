from autotest.client import os_dep
from autotest.client.shared import error, utils
from virttest import data_dir, env_process, virt_vm, utils_misc


@error.context_aware
def run(test, params, env):
    """
    Test tap device deleted after vm quit with error

    1) Boot a with invaild params.
    1) Check qemu-kvm quit with error.
    2) Check vm tap device delete from ovs bridge.

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    def get_ovs_ports(ovs):
        cmd = "ovs-vsctl list-ports %s" % ovs
        return set(utils.system_output(cmd).splitlines())

    os_dep.command("ovs-vsctl")
    netdst = params.get("netdst")
    if netdst not in utils.system_output("ovs-vsctl list-br"):
        raise error.TestError("%s isn't is openvswith bridge" % netdst)

    deps_dir = data_dir.get_deps_dir("ovs")
    nic_script = utils_misc.get_path(deps_dir, params["nic_script"])
    nic_downscript = utils_misc.get_path(deps_dir, params["nic_downscript"])
    params["nic_script"] = nic_script
    params["nic_downscript"] = nic_downscript

    params["qemu_command_prefix"] = "export SHELL=/usr/bin/bash;"
    params["start_vm"] = "yes"
    params["nettype"] = "bridge"
    params["nic_model"] = "virtio-net-pci"

    try:
        ports = get_ovs_ports(netdst)
        env_process.preprocess_vm(test, params, env, params["main_vm"])
        env.get_vm(params["main_vm"])
    except virt_vm.VMStartError:
        ports = get_ovs_ports(netdst) - ports
        if ports:
            for p in ports:
                utils.system("ovs-vsctl del-if %s %s" % (netdst, p))
            raise error.TestFail("%s not delete after qemu quit." % ports)
    else:
        raise error.TestFail("Qemu should quit with error")
