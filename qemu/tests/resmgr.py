from virttest.vt_cluster import cluster, selector
from virttest.vt_resmgr import resmgr


def run(test, params, env):
    def neg(f, **args):
        try:
            f(**args)
        except Exception as e:
            test.log.info("Exception: %s", str(e))

    def _setup_partition():
        partition = cluster.create_partition()
        for node in params.objects("nodes"):
            node_params = params.object_params(node)
            node_selectors = node_params.get("node_selectors")
            _node = selector.select_node(cluster.idle_nodes, node_selectors)
            if not _node:
                raise selector.SelectorError(
                    f'No available nodes for "{node}" with "{node_selectors}"'
                )
            _node.tag = node
            partition.add_node(_node)
        return partition

    def _cleanup_partition(partition):
        if partition.nodes:
            cluster.remove_partition(partition)

    cluster_partition = _setup_partition()
    test_volume = params["test_volume"]

    test.log.info("Create the volume %s step by step", test_volume)
    test_volume_id = resmgr.create_resource_from_params(
        test_volume, "volume", params.object_params(test_volume)
    )
    resmgr.bind_resource(test_volume_id)
    resmgr.update_resource(test_volume_id, "allocate")
    config = resmgr.get_resource_info(test_volume_id)
    test.log.info("test volume config: %s", config)

    test.log.info("Clone a new volume based on %s", test_volume)
    cloned_volume_uuid = resmgr.clone_resource(test_volume_id)
    cloned_volume_conf = resmgr.get_resource_info(cloned_volume_uuid)
    test.log.info("Cloned volume config: %s", cloned_volume_conf)
    cloned_volume_name = cloned_volume_conf["meta"]["name"]

    out = resmgr.get_resource_info(cloned_volume_uuid, "meta.pool")
    cloned_volume_pool = out["pool"]
    config = resmgr.get_pool_info(cloned_volume_pool)
    test.log.info("The cloned resource's pool config: %s", config)

    for target_pool_id, pool in resmgr.pools.items():
        if target_pool_id != cloned_volume_pool:
            break

    config = resmgr.get_pool_info(target_pool_id)
    test.log.info("Another resource's pool config: %s", config)

    test.log.info(
        "Create a new volume object based on %s from another pool %s",
        cloned_volume_name,
        config["meta"]["name"],
    )
    cp_volume_uuid = resmgr.create_resource_from_source(
        cloned_volume_uuid, target_pool_id
    )
    resmgr.bind_resource(cp_volume_uuid)
    resmgr.update_resource(cp_volume_uuid, "allocate")
    resmgr.update_resource(cp_volume_uuid, "sync")
    cp_volume_conf = resmgr.get_resource_info(cp_volume_uuid)
    test.log.info("Copied volume conf: %s", cp_volume_conf)

    # Negative testing
    test.log.info("Bind the copied resource again")
    neg(resmgr.bind_resource, resource_id=cp_volume_uuid, node_names=["node2"])

    test.log.info("Bind the copied resource to node1")
    neg(resmgr.bind_resource, resource_id=cp_volume_uuid, node_names=["node1"])

    resmgr.update_resource(cp_volume_uuid, "release")
    resmgr.unbind_resource(cp_volume_uuid)
    resmgr.destroy_resource(cp_volume_uuid)

    resmgr.update_resource(cloned_volume_uuid, "release")
    resmgr.unbind_resource(cloned_volume_uuid)
    resmgr.destroy_resource(cloned_volume_uuid)

    resmgr.update_resource(test_volume_id, "release")
    resmgr.unbind_resource(test_volume_id)
    resmgr.destroy_resource(test_volume_id)

    _cleanup_partition(cluster_partition)
