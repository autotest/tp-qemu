from virttest.vt_resmgr import resmgr


def run(test, params, env):
    # resource_id => bind => allocate/sync/release => unbind
    # call get_resource_info() to gain fds
    res_config = resmgr.define_resource_config("testcase", "port", params)
    test.log.info("pool_config: %s", str(res_config))

    resource_id = resmgr.create_resource_object(res_config)
    test.log.info("resource_id: %s", str(resource_id))

    resmgr.update_resource(resource_id, {"bind": {"nodes": ["host1"]}})
    test.log.info("bind...")

    resmgr.update_resource(resource_id, {"allocate": {}})
    test.log.info("After allocate...")

    # resmgr.update_resource(resource_id, {"sync": {}})
    # test.log.info("sync...")

    resource_info = resmgr.get_resource_info(resource_id)
    test.log.info("get_resource_info: %s", str(resource_info))
    try:
        # *********************************
        # Set fds in qemu cmdline on worker node.
        #
        # The following code is unnecessary.
        # *********************************
        # params["add_tapfd_nic1"] = resource_info["spec"]["fds"]
        # params["start_vm"] = "yes"
        # vm_name = params["main_vm"]
        #
        # env_process.preprocess_vm(test, params, env, vm_name)
        # vm = env.get_vm(vm_name)
        # vm.create()
        # vm.verify_alive()
        # vm.wait_for_login()
        # vm.destroy()
        pass
    finally:
        resmgr.update_resource(resource_id, {"release": {}})
        test.log.info("After release...")

        # resmgr.update_resource(resource_id, {"sync": {}})
        # test.log.info("sync...")

        resource_info = resmgr.get_resource_info(resource_id)
        test.log.info("get_resource_info: %s", str(resource_info))

        resmgr.update_resource(resource_id, {"unbind": {"nodes": []}})
        test.log.info("unbind...")
