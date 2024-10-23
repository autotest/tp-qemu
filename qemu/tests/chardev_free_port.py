from virttest import env_process, error_context, utils_misc

from qemu.tests.virtio_console import add_chardev


@error_context.context_aware
def run(test, params, env):
    """
    qemu should try to find a free port by to=<port> with unix socket and tcp options:
    1) boot guest with socket 'host=127.0.0.1,port=num'
    2) query chardev and check port number
    3) boot another guest with socket 'host=127.0.0.1,port=num,to=num+'
    4) query chardev and check port number, should different from 2)
    :param test: QEMU test object
    :param params: Dictionary with the test parameters
    :param env: Dictionary with test environment.
    """

    chardev_infos = []
    vms = params.get("vms").split()
    _vm = env.get_vm(vms[0])
    char_device = add_chardev(_vm, params)[0]
    chardev_params = char_device.params
    for vm_ind, vm in enumerate(vms):
        if vm_ind == 1:
            host = chardev_params["host"]
            chardev_to = utils_misc.find_free_ports(
                int(chardev_params["port"]) + 1, 6000, 1, host
            )
            chardev_params["to"] = str(chardev_to[0])

        extra_params = " " + char_device.cmdline()
        params["extra_params_%s" % vm] = params.get("extra_params", "") + extra_params
        params["start_vm_%s" % vm] = "yes"
    env_process.preprocess(test, params, env)
    for vm in vms:
        _vm = env.get_vm(vm)
        chardev_infos.append(_vm.monitor.info("chardev"))
    _port, _to = int(chardev_params["port"]), int(chardev_params["to"])
    for char_ind, chardevs in enumerate(chardev_infos):
        in_chardev = False
        for chardev in chardevs:
            if chardev["label"] == chardev_params["id"]:
                tmp_pnum = int(chardev["filename"].split(":")[-1].split(",")[0])
                error_context.context(
                    "Get port %d for vm%d from monitor" % (tmp_pnum, char_ind),
                    test.log.info,
                )
                break
        if char_ind == 0:
            error_context.context(
                "The expect port for vm%d is %d" % (char_ind, _port), test.log.info
            )
            if tmp_pnum == _port:
                in_chardev = True
        else:
            error_context.context(
                "The expect port for vm%d is in [%d, %d]" % (char_ind, _port + 1, _to),
                test.log.info,
            )
            if tmp_pnum > _port and tmp_pnum <= _to:
                in_chardev = True
        assert in_chardev is True, (
            "The actual port does not match with the expect port in VM %d" % char_ind
        )
