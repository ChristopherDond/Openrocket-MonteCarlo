from pathlib import Path

import jpype
import jpype.imports

BASE_DIR = Path(__file__).resolve().parents[1]
JAR_PATH = BASE_DIR / "assets" / "OpenRocket-15.03.jar"

jpype.startJVM(
    jpype.getDefaultJVMPath(),
    f"-Djava.class.path={JAR_PATH}",
    "--add-opens=java.base/java.lang=ALL-UNNAMED",
    convertStrings=False,
)

from net.sf.openrocket.startup import Application
print("OK — OpenRocket carregado")