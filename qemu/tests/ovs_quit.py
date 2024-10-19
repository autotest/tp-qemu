from virttest import (
    data_dir,
    env_process,
    error_context,
    utils_misc,
    utils_net,
    virt_vm,
)


@error_context.context_aware
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

    netdst = params.get("netdst")
    if not utils_net.ovs_br_exists(netdst):
        test.cancel("%s isn't an openvswith bridge" % netdst)

    host_bridge = utils_net.find_bridge_manager(netdst)
    deps_dir = data_dir.get_deps_dir("ovs")
    nic_script = utils_misc.get_path(deps_dir, params["nic_script"])
    nic_downscript = utils_misc.get_path(deps_dir, params["nic_downscript"])
    params["nic_script"] = nic_script
    params["nic_downscript"] = nic_downscript

    params["qemu_command_prefix"] = "export SHELL=/usr/bin/bash;"
    params["start_vm"] = "yes"
    params["nettype"] = "bridge"
    params["nic_model"] = "virtio-net-pci"

    ports = set(host_bridge.list_ports(netdst))
    try:
        env_process.preprocess_vm(test, params, env, params["main_vm"])
        env.get_vm(params["main_vm"])
    except virt_vm.VMCreateError:
        ports = set(host_bridge.list_ports(netdst)) - ports
        if ports:
            for p in ports:
                host_bridge.del_port(netdst, p)
            test.fail("%s not delete after qemu quit." % ports)
    else:
        test.fail("Qemu should quit with error")
