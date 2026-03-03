
case $1 in
  AliPhysics)
     cd .. 
     cat reproducer/alibuild_nix.jnj | python3 alibuild/aliBuild build AliPhysics --no-system abseil,re2,grpc,libuv,FreeType,Clang,zlib,expat --no-local re2,FairMQ,alibuild-recipe-tools,boost,arrow,FairLogger,ApMon-CPP,ROOT,GEANT3,fastjet,O2,MCStepLogger,DebugGUI,JAliEn-ROOT,O2,onnx,libuv,Clang --disable simulation --defaults o2 --plugin templating --disable CMake --debug > reproducer/alidist-aliphysics.nix
  ;;
  *) 
    cd .. 
    cat reproducer/alibuild_nix.jnj | python3 alibuild/aliBuild build Rivet --no-system abseil,re2,grpc,libuv,FreeType,Clang,zlib,expat,GSL --no-local re2,FairMQ,alibuild-recipe-tools,boost,arrow,FairLogger,ApMon-CPP,ROOT,GEANT3,fastjet,O2,MCStepLogger,DebugGUI,JAliEn-ROOT,O2,onnx,libuv,Clang,GEANT4,GSL,QualityControl --disable SHERPA,CMake --defaults o2 --plugin templating  --debug > reproducer/alidist.nix
  ;;
esac
