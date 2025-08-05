from virttest.vt_resmgr import resmgr


def run(test, params, env):
    test_volume = params["test_volume"]

    test.log.info("Now we create volume %s step by step", test_volume)
    conf = resmgr.define_resource_config(
        test_volume, "volume", params.object_params(test_volume)
    )
    test_volume_id = resmgr.create_resource_object(conf)
    resmgr.bind_resource_object(test_volume_id)
    resmgr.update_resource(test_volume_id, "allocate")
    test.log.info("test volume conf: %s", resmgr.get_resource_info(test_volume_id))

    test.log.info("Now we clone a new volume based on %s", test_volume)
    cloned_volume_uuid = resmgr.clone_resource(test_volume_id)
    cloned_volume_conf = resmgr.get_resource_info(cloned_volume_uuid)
    test.log.info("clone volume conf: %s", cloned_volume_conf)

    out = resmgr.get_resource_info(cloned_volume_uuid, "pool")
    cloned_volume_pool = out["pool"]
    for target_pool_id, pool in resmgr.pools.items():
        if target_pool_id != cloned_volume_pool:
            break
    test.log.info("Create a new volume object from another pool %s", target_pool_id)
    cp_volume_uuid = resmgr.create_resource_object_by(
        cloned_volume_uuid, target_pool_id
    )
    resmgr.bind_resource_object(cp_volume_uuid)
    resmgr.update_resource(cp_volume_uuid, "allocate")
    resmgr.update_resource(cp_volume_uuid, "sync")
    cp_volume_conf = resmgr.get_resource_info(cp_volume_uuid)
    test.log.info("cp volume conf: %s", cp_volume_conf)

    resmgr.update_resource(cp_volume_uuid, "release")
    resmgr.unbind_resource_object(cp_volume_uuid)
    resmgr.destroy_resource_object(cp_volume_uuid)

    resmgr.update_resource(cloned_volume_uuid, "release")
    resmgr.unbind_resource_object(cloned_volume_uuid)
    resmgr.destroy_resource_object(cloned_volume_uuid)

    resmgr.update_resource(test_volume_id, "release")
    resmgr.unbind_resource_object(test_volume_id)
    resmgr.destroy_resource_object(test_volume_id)
