from virttest import error_context


def props_dict(props):
    """
    Converts a list of property names
    into a dictionary compatible with the API call.

    :param props: A list of CPU property names
    """
    return {k: True if v == "True" else False for k, v in props.items()}


def not_found_expected_props(expected_props, props):
    """
    Returns the list containing all expected properties that
    were not found
    :param expected_props: List of expected property names
    :param props: Dictionary of obtained properties
    """
    return [x for x in expected_props if x not in props.keys()]


def found_unexpected_props(not_expected_props, props):
    """
    Returns the list containing all properties that were
    not expected to be found
    :param not_expected_props: List of not expected property names
    :param props: Dictionary of obtained properties
    """
    return [x for x in not_expected_props if x in props.keys()]


@error_context.context_aware
def run(test, params, env):
    """
    cpu-baseline will give the oldest model name and
    intersection of features.

    :param test: QEMU test object.
    :param params: Dictionary with test parameters.
    :param env: Dictionary with the test environment.
    """
    vm = env.get_vm(params["main_vm"])
    test.log.info("Start query cpu model supported by qmp")
    # get cpu models for test
    cpu_models = params.objects("cpu_models")
    props1 = props_dict(params.get_dict("props1"))
    props2 = props_dict(params.get_dict("props2"))
    expected_props = params.objects("expected_props")
    not_expected_props = params.objects("not_expected_props")
    test_failures = []
    for i in range(len(cpu_models)):
        newer_model = cpu_models[i]
        for j in range(i):
            older_model = cpu_models[j]

            args = {
                "modela": {"name": older_model, "props": props1},
                "modelb": {"name": newer_model, "props": props2},
            }
            test.log.debug("Test with args: %s", args)
            output = vm.monitor.cmd("query-cpu-model-baseline", args)

            obtained_model = output.get("model").get("name")
            expected_model = older_model + "-base"
            if obtained_model != expected_model:
                msg = (
                    "Expected to get older model but newer one"
                    " was chosen:"
                    " %s instead of expected %s."
                    " Input model names: %s and %s"
                    % (obtained_model, expected_model, older_model, newer_model)
                )
                test_failures.append(msg)

            props = output.get("model").get("props")
            found_not_expected = found_unexpected_props(not_expected_props, props)
            not_found_expected = not_found_expected_props(expected_props, props)

            if not_found_expected or found_not_expected:
                msg = (
                    "Expected to get intersection of props '%s'"
                    " and '%s': '%s';"
                    " but got '%s'" % (props1, props2, expected_props, props)
                )
                test_failures.append(msg)
    if test_failures:
        test.fail(
            "Some baselines didn't return as expected." " Details: %s" % test_failures
        )
