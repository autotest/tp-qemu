import ast

from virttest import error_context
from virttest.utils_misc import NumaInfo


@error_context.context_aware
def run(test, params, env):
    """
    Simple test to check if NUMA dist options are being parsed properly
    """
    vm = env.get_vm(params["main_vm"])
    vm.verify_alive()
    os_type = params["os_type"]
    session = vm.wait_for_login()
    if os_type == "windows":
        return

    expected_numa_dist = {}
    guest_numa_nodes = params.objects("guest_numa_nodes")
    for numa_node in guest_numa_nodes:
        numa_node_dist_value = ["unset" for i in range(len(guest_numa_nodes))]
        numa_params = params.object_params(numa_node)
        numa_nodeid = numa_params["numa_nodeid"]
        numa_dist = ast.literal_eval(numa_params.get("numa_dist", "[]"))
        for dist in numa_dist:
            dst_node = dist[0]
            distance_value = dist[1]
            numa_node_dist_value[dst_node] = str(distance_value)
        expected_numa_dist[int(numa_nodeid)] = numa_node_dist_value

    for src_id, dist_info in expected_numa_dist.items():
        # The distance from a node to itself is always 10
        dist_info[src_id] = "10"
        for dst_id, val in enumerate(dist_info):
            if val == "unset":
                # when distances are only given in one direction for each pair
                # of nodes, the distances in the opposite directions are assumed
                # to be the same
                expected_numa_dist[src_id][dst_id] = expected_numa_dist[dst_id][src_id]

    numa_info_guest = NumaInfo(session=session)
    session.close()

    guest_numa_dist = numa_info_guest.distances
    if guest_numa_dist != expected_numa_dist:
        test.fail(
            "The actual numa distance info in guest os is: %s, but the "
            "expected result is: %s" % (guest_numa_dist, expected_numa_dist)
        )
