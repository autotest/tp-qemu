from virttest import installer


def run(test, params, env):
    """
    Installs virtualization software using the selected installers

    :param test: test object.
    :param params: Dictionary with test parameters.
    :param env: Test environment.
    """
    workdir = params.get("workdir", test.workdir)
    params["workdir"] = workdir

    # Flag if a installer minor failure occurred
    minor_failure = False
    minor_failure_reasons = []

    for name in params.get("installers", "").split():
        installer_obj = installer.make_installer(name, params, test)
        installer_obj.install()
        installer_obj.write_version_keyval(test)
        if installer_obj.minor_failure is True:
            minor_failure = True
            reason = "%s_%s: %s" % (installer_obj.name,
                                    installer_obj.mode,
                                    installer_obj.minor_failure_reason)
            minor_failure_reasons.append(reason)

    if minor_failure:
        test.error("Minor (worked around) failures during build "
                   "test: %s" % ", ".join(minor_failure_reasons))
