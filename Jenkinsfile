node ("slc7_x86-64-light") {

  stage "Simple tests"

  def test_script = """
      rm -fr alibuild alidist
      git clone https://github.com/alisw/alibuild
      git clone https://github.com/alisw/alidist
      alibuild/aliBuild --help
      alibuild/aliBuild -d build zlib
    """

  parallel(
    "slc7": {
      node ("slc7_x86-64-light") {
        sh test_script
      }
    },
    "ubuntu1510": {
      node ("ubt1510_x86-64-light") {
        sh test_script
      }
    }
  )
}
