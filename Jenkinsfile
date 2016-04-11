#!groovy

node {

  stage "Verify author"
  def power_users = ["ktf", "dberzano"]
  echo "Changeset from " + env.CHANGE_AUTHOR
  if (power_users.contains(env.CHANGE_AUTHOR)) {
    echo "PR comes from power user. Testing"
  } else {
    input "Do you want to test this change?"
  }
  
  stage "Simple tests"
  def test_script = """
      ls
      (cd alibuild && git show)
      alibuild/aliBuild --help
      rm -fr alidist
      git clone https://github.com/alisw/alidist
      alibuild/aliBuild -d build zlib
    """

  parallel(
    "slc7": {
      node ("slc7_x86-64-light") {
        dir ("alibuild") {
          checkout scm
        }
        sh test_script
      }
    },
    "ubuntu1510": {
      node ("ubt1510_x86-64-light") {
        dir ("alibuild") {
          checkout scm
        }
        sh test_script
      }
    }
  )
}
