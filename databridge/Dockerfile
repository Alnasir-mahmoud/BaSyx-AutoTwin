# Eclipse BaSyx DataBridge — https://github.com/eclipse-basyx/basyx-databridge
# Runtime container for the official BaSyx DataBridge (Java).
# The JAR and lib/ are taken from the Eclipse BaSyx project (Apache 2.0 License).
# Customised here: base image changed from milestone-08 to eclipse-temurin:11 +
#   SNAPSHOT jar + manual PLC4X Modbus driver add (milestone-08 has a Modbus polling bug).
FROM eclipse-temurin:11

# SNAPSHOT DataBridge executable (the milestone-08 one has the PLC4X Modbus polling bug)
COPY databridge.component-1.0.0-SNAPSHOT.jar /usr/share/databridgeExecutable.jar

# All runtime JARs (basyx, camel, plc4j, netty, jackson, ...)
COPY lib/ /usr/share/lib/

# Add Apache PLC4X 0.10.0 Modbus driver from github.com/apache/plc4x (Maven Central)
ADD https://repo1.maven.org/maven2/org/apache/plc4x/plc4j-driver-modbus/0.10.0/plc4j-driver-modbus-0.10.0.jar /usr/share/lib/
ADD https://repo1.maven.org/maven2/org/apache/plc4x/plc4j-transport-tcp/0.10.0/plc4j-transport-tcp-0.10.0.jar /usr/share/lib/
ADD https://repo1.maven.org/maven2/com/github/jinahya/bit-io/1.4.3/bit-io-1.4.3.jar /usr/share/lib/

EXPOSE 8085

CMD ["java", "-cp", "/usr/share/databridgeExecutable.jar:/usr/share/lib/*", \
     "org.eclipse.digitaltwin.basyx.databridge.component.DataBridgeExecutable"]
