from avocado import fail_on
from virttest import utils_misc


@fail_on
def job_dismiss(vm, job_id):
    """Dismiss block job in the given VM"""
    job = get_job_by_id(vm, job_id)
    msg = "Job '%s' is '%s', only concluded job can dismiss!" % (
        job_id, job["status"])
    assert job["status"] == "concluded", msg
    func = utils_misc.get_monitor_function(vm)
    return func(job_id)


def get_job_by_id(vm, job_id):
    """Get block job info by job ID"""
    jobs = query_jobs(vm)
    info = [j for j in jobs if j["id"] == job_id]
    if info:
        return info[0]
    return None


def query_jobs(vm):
    """Get block jobs info list in given VM"""
    func = utils_misc.get_monitor_function(vm)
    return func()
