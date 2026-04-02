import jpype
import jpype.imports

jpype.startJVM(
    jpype.getDefaultJVMPath(),
    "-Djava.class.path=OpenRocket-15.03.jar",
    "--add-opens=java.base/java.lang=ALL-UNNAMED",
    convertStrings=False,
)

from net.sf.openrocket.startup import Application
print("OK — OpenRocket carregado")