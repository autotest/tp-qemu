from virttest.vt_resmgr import resmgr


def run(test, params, env):
    # resource_id => bind => allocate/sync/release => unbind
    # call get_resource_info() to gain fds
    # set fds to add_tapfd_nic
    # start_vm = yes and boot vm
    # login vm
    # quit
    res_config = resmgr.define_resource_config("testcase", "port", params)
    test.log.info("pool_config: %s", str(res_config))

    resource_id = resmgr.create_resource_object(res_config)
    test.log.info("resource_id: %s", str(resource_id))

    resmgr.update_resource(resource_id, {"bind": {"nodes": ["host1"]}})
    test.log.info("bind: ")

    resource_info = resmgr.update_resource(resource_id, {"allocate": {}})
    test.log.info("After allocate, resource_info: %s", str(resource_info))

    params["add_tapfd_nic1"] = resource_info["spec"]["fds"]
    params["start_vm"] = "yes"
    vm_name = params["main_vm"]

    env.preprocess_vm(test, params, env, vm_name)
    vm = env.get_vm(vm_name)
    vm.wait_for_login()
    vm.destroy()

    resource_info = resmgr.update_resource(resource_id, {"release": {}})
    test.log.info("After release, resource_info: %s", str(resource_info))

    resmgr.update_resource(resource_id, {"unbind": {"nodes": []}})
    test.log.info("unbind: ")

    resmgr.update_resource(resource_id, {"destroy": {}})
    test.log.info("destroy: ")
