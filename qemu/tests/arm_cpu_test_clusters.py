import random

from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    Check guest gets correct multiple vcpu clusters

    1) Boot guest with options: -smp n,clusters=2x...
    2) Check cpu clusters(only for Linux guest)

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    vcpu_clusters_list = [2, 4]
    params["vcpu_clusters"] = random.choice(vcpu_clusters_list)
    params["start_vm"] = "yes"
    vm.create(params=params)
    vm.verify_alive()
    session = vm.wait_for_login()

    check_cluster_id = params["check_cluster_id"]
    check_cluster_cpus_list = params["check_cluster_cpus_list"]
    vcpu_sockets = vm.cpuinfo.sockets
    vcpu_clusters = vm.cpuinfo.clusters
    clusters_id = session.cmd_output(check_cluster_id).strip().splitlines()
    clusters_cpus_list = (
        session.cmd_output(check_cluster_cpus_list).strip().splitlines()
    )
    if len(clusters_id) != int(vcpu_clusters):
        test.fail(
            "cluster_id is not right: %d != %d" % (len(clusters_id), int(vcpu_clusters))
        )
    if len(clusters_cpus_list) != int(vcpu_sockets) * int(vcpu_clusters):
        test.fail(
            "cluster_cpus_list is not right: %d != %d"
            % (len(clusters_cpus_list), int(vcpu_sockets) * int(vcpu_clusters))
        )

    vm.verify_kernel_crash()
    session.close()
    vm.destroy()
