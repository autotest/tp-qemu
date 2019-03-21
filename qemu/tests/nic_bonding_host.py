import time
import logging
import re

from avocado.utils import process

from virttest import error_context
from virttest import utils_test
from virttest import utils_misc
from virttest import env_process
from virttest import utils_net


@error_context.context_aware
def run(test, params, env):
    """
    Qemu host nic bonding test:
    1) Load bonding module with mode 802.3ad
    2) Bring up bond interface
    3) Add nics to bond interface
    4) Add a new bridge and add bond interface to it
    5) Get ip address for bridge
    6) Boot up guest with the bridge
    7) Checking guest netowrk via ping
    8) Start file transfer between guest and host
    9) Disable and enable physical interfaces during file transfer

    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """
    bond_iface = params.get("bond_iface", "bond0")
    bond_br_name = params.get("bond_br_name", "br_bond0")
    timeout = int(params.get("login_timeout", 240))
    remote_host = params.get("dsthost")
    ping_timeout = int(params.get("ping_timeout", 240))
    bonding_timeout = int(params.get("bonding_timeout", 1))
    bonding_mode = params.get("bonding_mode", "1")
    bonding_miimon = params.get("bonding_miimon", "100")
    bonding_max_bonds = params.get("bonding_max_bonds", "1")
    params['netdst'] = bond_br_name
    host_bridges = utils_net.Bridge()

    error_context.context("Load bonding module with mode 802.3ad",
                          logging.info)
    if not process.system("lsmod|grep bonding", ignore_status=True,
                          shell=True):
        process.system("modprobe -r bonding")

    process.system("modprobe bonding mode=%s miimon=%s max_bonds=%s" %
                   (bonding_mode, bonding_miimon, bonding_max_bonds))

    error_context.context("Bring up %s" % bond_iface, logging.info)
    host_ifaces = utils_net.get_host_iface()

    if bond_iface not in host_ifaces:
        test.error("Can not find %s in host" % bond_iface)

    bond_iface = utils_net.Interface(bond_iface)
    bond_iface.up()
    bond_mac = bond_iface.get_mac()

    host_ph_iface_pre = params.get("host_ph_iface_prefix", "en")
    host_iface_bonding = int(params.get("host_iface_bonding", 2))

    ph_ifaces = [_ for _ in host_ifaces if re.match(host_ph_iface_pre, _)]
    host_ph_ifaces = [_ for _ in ph_ifaces if utils_net.Interface(_).is_up()]

    ifaces_in_use = host_bridges.list_iface()
    host_ph_ifaces_un = list(set(host_ph_ifaces) - set(ifaces_in_use))

    if (len(host_ph_ifaces_un) < 2 or
            len(host_ph_ifaces_un) < host_iface_bonding):
        test.cancel("Host need %s nics at least." % host_iface_bonding)

    error_context.context("Add nics to %s" % bond_iface.name, logging.info)
    host_ifaces_bonding = host_ph_ifaces_un[:host_iface_bonding]
    ifenslave_cmd = "ifenslave %s" % bond_iface.name
    op_ifaces = []
    for host_iface_bonding in host_ifaces_bonding:
        op_ifaces.append(utils_net.Interface(host_iface_bonding))
        ifenslave_cmd += " %s" % host_iface_bonding
    process.system(ifenslave_cmd)

    error_context.context("Add a new bridge and add %s to it."
                          % bond_iface.name, logging.info)
    if bond_br_name not in host_bridges.list_br():
        host_bridges.add_bridge(bond_br_name)
    host_bridges.add_port(bond_br_name, bond_iface.name)

    error_context.context("Get ip address for bridge", logging.info)
    process.system("dhclient -r; dhclient %s" % bond_br_name, shell=True)

    error_context.context("Boot up guest with bridge %s" % bond_br_name,
                          logging.info)
    params["start_vm"] = "yes"
    vm_name = params.get("main_vm")
    env_process.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    session = vm.wait_for_login(timeout=timeout)

    error_context.context("Checking guest netowrk via ping.", logging.info)
    ping_cmd = params.get("ping_cmd")
    ping_cmd = re.sub("REMOTE_HOST", remote_host, ping_cmd)
    session.cmd(ping_cmd, timeout=ping_timeout)

    error_context.context("Start file transfer", logging.info)
    f_transfer = utils_misc.InterruptedThread(
        utils_test.run_virt_sub_test,
        args=(test, params, env,),
        kwargs={"sub_type": "file_transfer"})
    f_transfer.start()
    utils_misc.wait_for(
        lambda: process.system_output("pidof scp", ignore_status=True), 30)

    error_context.context("Disable and enable physical "
                          "interfaces in %s" % bond_br_name, logging.info)
    while True:
        for op_iface in op_ifaces:
            logging.debug("Turn down %s" % op_iface.name)
            op_iface.down()
            time.sleep(bonding_timeout)
            logging.debug("Bring up %s" % op_iface.name)
            op_iface.up()
            time.sleep(bonding_timeout)
        if not f_transfer.is_alive():
            break
    f_transfer.join()
