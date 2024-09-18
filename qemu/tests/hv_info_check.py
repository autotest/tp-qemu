from virttest import error_context


@error_context.context_aware
def run(test, params, env):
    """
    HyperV Enlightenments info query test:

    1) Boot guest.
    2) Query supported HyperV Enlightenments by host.
    """
    cpu_model_flags = params["cpu_model_flags"]

    vm = env.get_vm(params["main_vm"])
    error_context.context(
        "Query supported HyperV Enlightenments " "by host", test.log.info
    )
    missing = []
    args = {
        "type": "full",
        "model": {"name": "host", "props": {"hv-passthrough": True}},
    }
    output = vm.monitor.cmd("query-cpu-model-expansion", args)
    model = output.get("model")
    model_prop = model.get("props")
    cpu_model_flags = cpu_model_flags.replace("_", "-")
    cpu_model_flags = [i for i in cpu_model_flags.split(",") if "hv" in i]
    for flag in cpu_model_flags:
        if "hv-spinlocks" in flag:
            continue
        if model_prop.get(flag) is not True:
            missing.append(flag)
    if missing:
        test.fail("Check cpu model props failed, %s is not True" % missing)
