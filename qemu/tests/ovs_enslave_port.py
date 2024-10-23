from avocado.utils import process
from virttest import error_context, utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Enslave a port which is already a member of ovs into another

    1) Check current ovs bridge and list the ports in it
    2) Create a new ovs bridge
    3) Enslave one port which is a member of current ovs bridge
       into the new one
    4) Delete the new ovs bridge

    :param test: Kvm test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    netdst = params["netdst"]
    if utils_net.ovs_br_exists(netdst) is not True:
        test.cancel("%s isn't an openvswith bridge" % netdst)

    new_br_name = params.get("new_ovs_bridge_name", "temp_ovs_bridge")
    host_bridge = utils_net.find_bridge_manager(netdst)
    if host_bridge.br_exist(new_br_name) is True:
        host_bridge.del_br(new_br_name)
    host_bridge.add_br(new_br_name)
    error_context.context("OVS bridge %s created." % new_br_name, test.log.info)

    try:
        ports = host_bridge.list_ports(netdst)
        host_bridge.add_port(new_br_name, ports[0])
    except process.CmdError as e:
        if "already exists on bridge" not in e.result.stderr_text:
            test.fail(
                "Port %s should not be enslaved to another bridge."
                " Output: %s" % (ports[0], e.result.stderr_text)
            )
    else:
        test.fail(
            "Add port cmd successfully excuted. However, port %s "
            "should not be enslaved to another bridge." % ports[0]
        )
    finally:
        host_bridge.del_br(new_br_name)
