#!/bin/bash -e

echo "Running commits message check..."
exit_code=0
readarray -t commits <<< $(git log --no-merges -n "${COMMIT_COUNT}" --format='%H')
for commit in "${commits[@]}"; do
  AUTHOR=$(git log -1 --format='%aN <%aE>' "${commit}")
  HEADER=$(git log -1 --format='%s' "${commit}")
  echo "Commit check for sha: '${commit}'"
  echo "The header of commit is: '${HEADER}'"
  # Check header length
  if [ $(echo "${HEADER}" | wc -L) -gt 72 ]; then
    echo "The commit header is longer than 72 characters"
    exit_code=1
  fi
  # Check if commit header ends with '.' or ' '
  if [[ "${HEADER}" =~ ( $|\.$) ]]; then
    echo "The commit header ends with '.' or ' '"
    exit_code=1
  fi
  # Check if commit message contains author's signature
  if ! git log -1 --format='%b' "${commit}" | grep -qi "^Signed-off-by: ${AUTHOR}"; then
    echo "The commit does not contain author's signature (Signed-off-by: ${AUTHOR})"
    exit_code=1
  fi
done

if [ "${exit_code}" -ne 0 ]; then
  guide="https://avocado-framework.readthedocs.io/en/latest/guides/contributor/chapters/styleguides.html#commit-style-guide"
  echo "Please refer to ${guide} to correct your commit(s)"
fi
exit ${exit_code}
