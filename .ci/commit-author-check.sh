#!/bin/bash -e

echo "** Running author-check..."
COMMIT_COUNT="${COMMIT_COUNT:-1}"

exit_code=0
blacklist=("root")

readarray -t commits <<< $(git log --no-merges -n "${COMMIT_COUNT}" --format='%H')
for commit in "${commits[@]}"; do
  AUTHOR=$(git show --format='%aN' --no-patch "${commit}")
  echo "Checking commit: ${commit}"
  # shellcheck disable=SC2076
  if [[ " ${blacklist[*]} " =~ ${AUTHOR} ]]; then
    echo -e "The commit author should not be ${AUTHOR}\n"
    exit_code=1
  else
    echo -e "The commit author is not in the blacklist\n"
  fi
done

if [ "${exit_code}" -ne 0 ]; then
  guide="https://avocado-framework.readthedocs.io/en/latest/guides/contributor/chapters/how.html#git-workflow"
  echo "Please refer to ${guide} to correct your commit(s)"
fi
exit ${exit_code}
