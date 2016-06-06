#!groovy

node {
  stage "Verify author"
  def power_users = ["ktf", "dberzano"]
  echo "Changeset from " + env.CHANGE_AUTHOR

  if (power_users.contains(env.CHANGE_AUTHOR)) {
    echo "PR comes from power user. Testing"
    slackSend channel: '#github',
              color: 'good',
              message: "Automatically testing new PR in Jenkins.\nhttps://alijenkins.cern.ch/job/alibuild-pipeline/branch/${env.BRANCH_NAME} for progress report.",
              token: env.SLACK_TOKEN
  } else {
    withCredentials([[$class: 'StringBinding', credentialsId: 'SLACK_TOKEN', variable: 'SLACK_TOKEN']]) {
      slackSend channel: '#github',
                color: 'good',
                message: "A new PR to be approved for aliBuild. Please check https://alijenkins.cern.ch/job/alibuild-pipeline/branch/${env.BRANCH_NAME}",
                token: env.SLACK_TOKEN
      input "Do you want to test this change?"
    }
  }

  stage "Run tests"
  def build_script = '''
      (cd alibuild && git show && git log HEAD~5..)
      alibuild/aliBuild --help
      rm -fr alidist
      git clone https://github.com/alisw/alidist
      CHANGED_FILES=`cd alibuild && git diff --name-only origin/$CHANGE_TARGET.. | sed -e 's|/.*||' | sort -u`
      for d in $CHANGED_FILES; do
        case $d in
          # Changes in alibuild_helpers can we tested in isolation, so we
          # do so.
          alibuild_helpers|tests)
            PYTHONPATH=alibuild python alibuild/tests/test_utilities.py
            PYTHONPATH=alibuild python alibuild/tests/test_analytics.py
            ;;
          # Changes to alibuild require a full rebuild to be validated. The
          # goal as usual is to fail fast.
          aliBuild)
            alibuild/aliBuild -d build zlib
            alibuild/aliBuild --reference-sources /build/mirror -d build AliRoot -n
            ;;
          # All the other changes we do not have tests right now.
          *) ;;
        esac
      done

      # We do more extensive tests later
      for d in $CHANGED_FILES; do
        case $d in
          # Rebuild everything if aliBuild or build_template.sh changed
          aliBuild|*build_template.sh)
            alibuild/aliBuild --reference-sources /build/mirror --remote-store rsync://repo.marathon.mesos/store/ -d build AliRoot
            ;;
          # All the other changes we do not have tests right now.
          *) ;;
        esac
      done
    '''

    withEnv(["CHANGED_TARGET=${env.CHANGE_TARGET}"]) {
      parallel(
        "slc5": {
          node ("slc5_x86-64-large") {
            dir ("alibuild") {
              checkout scm
            }
            sh build_script
          }
        },
        "slc6": {
          node ("slc6_x86-64-large") {
            dir ("alibuild") {
              checkout scm
            }
            sh build_script
          }
        },
        "slc7": {
          node ("slc7_x86-64-large") {
            dir ("alibuild") {
              checkout scm
            }
            sh build_script
          }
        },
        "ubuntu1510": {
          node ("ubt1510_x86-64-large") {
            dir ("alibuild") {
              checkout scm
            }
            sh build_script
          }
        }
      )
    }
}
