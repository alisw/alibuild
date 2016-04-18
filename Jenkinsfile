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
  
  stage "Simple tests"
  def test_script = """
      (cd alibuild && git show && git log HEAD~5..)
      alibuild/aliBuild --help
      rm -fr alidist
      git clone https://github.com/alisw/alidist
      alibuild/aliBuild -d build zlib
      alibuild/aliBuild --reference-sources /build/mirror -d build AliRoot -n
    """

    node ("slc7_x86-64-light") {
      dir ("alibuild") {
        checkout scm
      }
      sh test_script
    }

  stage "Full build"
  def full_build_script = """
      (cd alibuild && git show && git log HEAD~5..)
      alibuild/aliBuild --help
      rm -fr alidist
      git clone https://github.com/alisw/alidist
      alibuild/aliBuild --reference-sources /build/mirror --debug --remote-store rsync://repo.marathon.mesos/store/ -d build AliRoot
    """
  parallel(
    "slc5": {
      node ("slc5_x86-64-large") {
        dir ("alibuild") {
          checkout scm
        }
        sh full_build_script
      }
    },
    "slc7": {
      node ("slc7_x86-64-large") {
        dir ("alibuild") {
          checkout scm
        }
        sh full_build_script
      }
    },
    "ubuntu1510": {
      node ("ubt1510_x86-64-large") {
        dir ("alibuild") {
          checkout scm
        }
        sh full_build_script
      }
    }
  )
 
}
