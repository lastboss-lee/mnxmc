# Runtime Snapshot (captured 2026-07-10 10:35:26)

본 문서는 분석 시점의 실제 런타임 상태 스냅샷이다. 모든 근거는 실행 결과에 기반한다.

## df -h
```
Filesystem      Size  Used Avail Use% Mounted on
/dev/sda3       187G   37G  143G  21% /
/dev/sdc1        49G   28G   20G  59% /pipeline
/dev/sda2       9.8G  133M  9.1G   2% /boot
/dev/sdb3        15G  414M   14G   3% /docker
/dev/sdb2       9.8G  160K  9.3G   1% /dir_cache
/dev/sdd2        40G   31G  9.4G  77% /data
/dev/sdd1        20G   19G  1.9G  91% /application
overlay         187G   37G  143G  21% /docker/rootfs/overlayfs/2beb10e5664c65f632ef0e6a46766567220977c4820dc5759c05b1e62301b453
overlay         187G   37G  143G  21% /docker/rootfs/overlayfs/8e17ecc7c9b746eb2efb43ad54f2d8ac0eb46d5d2a40105ef8cfc7176f352e04
/dev/sdb4        30G  9.7G   19G  35% /logs
```

## /data & /logs usage
```
0	/data/dga_result
109M	/data/mnxmc-2.1.3.deb
109M	/data/mnxmc-2.1.4.deb
127M	/data/mnxmc-2.2.0.deb
0	/data/payload
31G	/data/raw
108K	/data/tools
123M	/logs/eng_monitor
385M	/logs/kafka
16K	/logs/lost+found
8.4G	/logs/mnxcapture
459M	/logs/mnxdpi
52M	/logs/mnx_web
6.0M	/logs/payload_ai_analysis
5.2M	/logs/payload_analysis
7.0M	/logs/payload_scanengine
2.9M	/logs/service_control
260M	/logs/suricata
664K	/logs/syslog
16K	/var/log/mnx
```

## MNX systemd unit states
```
elasticsearch            enabled=enabled   active=active
kafka                    enabled=disabled  active=active
zookeeper                enabled=disabled  active=active
mnxcapture               enabled=enabled   active=active
mnxdpi                   enabled=disabled  active=active
mnx_payload              enabled=enabled   active=active
mnx_payload_ai           enabled=disabled  active=active
mnx_payload_scan         enabled=disabled  active=active
mnx_regression_api       enabled=enabled   active=active
mnx_service_control      enabled=enabled   active=active
eng_monitor              enabled=enabled   active=active
promisc-ens192           enabled=enabled   active=active
suricata                 enabled=enabled   active=active
rsyslog                  enabled=enabled   active=active
```

## Full listening ports (ss -tlnp)
```
State Recv-Q Send-Q Local Address:Port Peer Address:PortProcess 
LISTEN 0 128 127.0.0.1:22881 0.0.0.0:* users:(("code-7e7950df89",pid=23539,fd=11)) 
LISTEN 0 4096 127.0.0.1:24349 0.0.0.0:* users:(("containerd",pid=1148,fd=15)) 
LISTEN 0 128 127.0.0.1:19883 0.0.0.0:* users:(("code-7e7950df89",pid=23503,fd=10)) 
LISTEN 0 4096 0.0.0.0:111 0.0.0.0:* users:(("rpcbind",pid=1006,fd=4),("systemd",pid=1,fd=36)) 
LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=2293,fd=6),("nginx",pid=2292,fd=6),("nginx",pid=2291,fd=6),("nginx",pid=2290,fd=6),("nginx",pid=2289,fd=6),("nginx",pid=2288,fd=6),("nginx",pid=2287,fd=6),("nginx",pid=2286,fd=6),("nginx",pid=2285,fd=6),("nginx",pid=2284,fd=6),("nginx",pid=2283,fd=6),("nginx",pid=2282,fd=6),("nginx",pid=2254,fd=6)) 
LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=1162,fd=3)) 
LISTEN 0 511 0.0.0.0:443 0.0.0.0:* users:(("nginx",pid=2293,fd=10),("nginx",pid=2292,fd=10),("nginx",pid=2291,fd=10),("nginx",pid=2290,fd=10),("nginx",pid=2289,fd=10),("nginx",pid=2288,fd=10),("nginx",pid=2287,fd=10),("nginx",pid=2286,fd=10),("nginx",pid=2285,fd=10),("nginx",pid=2284,fd=10),("nginx",pid=2283,fd=10),("nginx",pid=2282,fd=10),("nginx",pid=2254,fd=10))
LISTEN 0 5 0.0.0.0:8000 0.0.0.0:* users:(("python3.12",pid=18814,fd=13)) 
LISTEN 0 511 0.0.0.0:8090 0.0.0.0:* users:(("nginx",pid=2293,fd=8),("nginx",pid=2292,fd=8),("nginx",pid=2291,fd=8),("nginx",pid=2290,fd=8),("nginx",pid=2289,fd=8),("nginx",pid=2288,fd=8),("nginx",pid=2287,fd=8),("nginx",pid=2286,fd=8),("nginx",pid=2285,fd=8),("nginx",pid=2284,fd=8),("nginx",pid=2283,fd=8),("nginx",pid=2282,fd=8),("nginx",pid=2254,fd=8)) 
LISTEN 0 128 127.0.0.1:6011 0.0.0.0:* users:(("sshd",pid=10858,fd=7)) 
LISTEN 0 128 127.0.0.1:6010 0.0.0.0:* users:(("sshd",pid=3093,fd=7)) 
LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:* users:(("systemd-resolve",pid=1058,fd=14)) 
LISTEN 0 80 127.0.0.1:3306 0.0.0.0:* users:(("mariadbd",pid=1347,fd=27)) 
LISTEN 0 511 127.0.0.1:44114 0.0.0.0:* users:(("MainThread",pid=23619,fd=38)) 
LISTEN 0 100 *:8443 *:* users:(("java",pid=2294,fd=189)) 
LISTEN 0 4096 *:9200 *:* users:(("java",pid=15810,fd=313)) 
LISTEN 0 50 *:9092 *:* users:(("java",pid=17016,fd=212)) 
LISTEN 0 4096 *:9300 *:* users:(("java",pid=15810,fd=311)) 
LISTEN 0 50 *:12045 *:* users:(("java",pid=17016,fd=129)) 
LISTEN 0 50 *:14029 *:* users:(("java",pid=16373,fd=129)) 
LISTEN 0 4096 [::]:111 [::]:* users:(("rpcbind",pid=1006,fd=6),("systemd",pid=1,fd=38)) 
LISTEN 0 511 [::]:80 [::]:* users:(("nginx",pid=2293,fd=7),("nginx",pid=2292,fd=7),("nginx",pid=2291,fd=7),("nginx",pid=2290,fd=7),("nginx",pid=2289,fd=7),("nginx",pid=2288,fd=7),("nginx",pid=2287,fd=7),("nginx",pid=2286,fd=7),("nginx",pid=2285,fd=7),("nginx",pid=2284,fd=7),("nginx",pid=2283,fd=7),("nginx",pid=2282,fd=7),("nginx",pid=2254,fd=7)) 
LISTEN 0 128 [::]:22 [::]:* users:(("sshd",pid=1162,fd=4)) 
LISTEN 0 511 [::]:443 [::]:* users:(("nginx",pid=2293,fd=11),("nginx",pid=2292,fd=11),("nginx",pid=2291,fd=11),("nginx",pid=2290,fd=11),("nginx",pid=2289,fd=11),("nginx",pid=2288,fd=11),("nginx",pid=2287,fd=11),("nginx",pid=2286,fd=11),("nginx",pid=2285,fd=11),("nginx",pid=2284,fd=11),("nginx",pid=2283,fd=11),("nginx",pid=2282,fd=11),("nginx",pid=2254,fd=11))
LISTEN 0 50 *:2181 *:* users:(("java",pid=16373,fd=141)) 
LISTEN 0 511 [::]:8090 [::]:* users:(("nginx",pid=2293,fd=9),("nginx",pid=2292,fd=9),("nginx",pid=2291,fd=9),("nginx",pid=2290,fd=9),("nginx",pid=2289,fd=9),("nginx",pid=2288,fd=9),("nginx",pid=2287,fd=9),("nginx",pid=2286,fd=9),("nginx",pid=2285,fd=9),("nginx",pid=2284,fd=9),("nginx",pid=2283,fd=9),("nginx",pid=2282,fd=9),("nginx",pid=2254,fd=9)) 
LISTEN 0 128 [::1]:6010 [::]:* users:(("sshd",pid=3093,fd=5)) 
LISTEN 0 128 [::1]:6011 [::]:* users:(("sshd",pid=10858,fd=5)) 
```

## MNX-related processes (ps)
```
   1065       1 message+  0.0  0.0  4856 Ss   @dbus-daemon --system --address=systemd: --nofork --nopidfile --systemd-activation --syslog-only
   1093       1 syslog    0.0  0.0  5736 Ssl  /usr/sbin/rsyslogd -n -iNONE
   1347       1 mysql     0.0  0.2 136908 Ssl /usr/sbin/mariadbd
   2254    2199 root      0.0  0.0  6992 Ss   nginx: master process nginx -g daemon off;
   2282    2254 systemd+  0.0  0.0  2848 S    nginx: worker process
   2283    2254 systemd+  0.0  0.0  2848 S    nginx: worker process
   2284    2254 systemd+  0.0  0.0  2848 S    nginx: worker process
   2285    2254 systemd+  0.0  0.0  2848 S    nginx: worker process
   2286    2254 systemd+  0.0  0.0  2848 S    nginx: worker process
   2287    2254 systemd+  0.0  0.0  2848 S    nginx: worker process
   2288    2254 systemd+  0.0  0.0  2848 S    nginx: worker process
   2289    2254 systemd+  0.0  0.0  2848 S    nginx: worker process
   2290    2254 systemd+  0.0  0.0  2848 S    nginx: worker process
   2291    2254 systemd+  0.0  0.0  2848 S    nginx: worker process
   2292    2254 systemd+  0.0  0.0  2848 S    nginx: worker process
   2293    2254 systemd+  0.0  0.0  2848 S    nginx: worker process
   4020       1 root      0.7  0.0 38556 Ssl+ /usr/bin/python3.12 /mnxmc/main-login.py
  15585       1 root      0.0  0.0  5936 Ssl  /opt/service_control/service_control -d -c /opt/mnx/etc/mnx_config.json
  15810       1 elastic+ 74.3  9.8 5051556 SLsl /usr/share/elasticsearch/jdk/bin/java -Xshare:auto -Des.networkaddress.cache.ttl=60 -Des.networkaddress.cache.negative.ttl=10 -XX:+AlwaysPreTouch -Xss1m -Djava.awt.headless=true -Dfile.encoding=UTF-8 -Djna.nosys=true -XX:-OmitStackTraceInFastThrow -XX:+ShowCodeDetailsInExceptionMessages -Dio.netty.noUnsafe=true -Dio.netty.noKeySetOptimization=true -Dio.netty.recycler.maxCapacityPerThread=0 -Dio.netty.allocator.numDirectArenas=0 -Dlog4j.shutdownHookEnabled=false -Dlog4j2.disable.jmx=true -Dlog4j2.formatMsgNoLookups=true -Djava.locale.providers=SPI,COMPAT --add-opens=java.base/java.io=ALL-UNNAMED -Djava.security.manager=allow -Xms4g -Xmx4g -XX:+UseG1GC -Djava.io.tmpdir=/tmp/elasticsearch-11439107646269758526 -XX:+HeapDumpOnOutOfMemoryError -XX:+ExitOnOutOfMemoryError -XX:HeapDumpPath=/var/lib/elasticsearch -XX:ErrorFile=/var/log/elasticsearch/hs_err_pid%p.log -Xlog:gc*,gc+age=trace,safepoint:file=/var/log/elasticsearch/gc.log:utctime,pid,tags:filecount=32,filesize=64m -XX:+UnlockDiagnosticVMOptions -XX:G1NumCollectionsKeepPinned=10000000 -XX:MaxDirectMemorySize=2147483648 -XX:G1HeapRegionSize=4m -XX:InitiatingHeapOccupancyPercent=30 -XX:G1ReservePercent=15 -Des.path.home=/usr/share/elasticsearch -Des.path.conf=/etc/elasticsearch -Des.distribution.flavor=default -Des.distribution.type=deb -Des.bundled_jdk=true -cp /usr/share/elasticsearch/lib/* org.elasticsearch.bootstrap.Elasticsearch -p /var/run/elasticsearch/elasticsearch.pid --quiet
  16022   15810 elastic+  0.0  0.0  7008 Sl   /usr/share/elasticsearch/modules/x-pack-ml/platform/linux-x86_64/bin/controller
  16120       1 root      0.2  0.0  3656 Ss   /bin/bash /data/tools/eng_monitor.sh
  16373       1 root      0.1  0.1 101432 Ssl /usr/share/elasticsearch/jdk//bin/java -Xmx512M -Xms512M -server -XX:+UseG1GC -XX:MaxGCPauseMillis=20 -XX:InitiatingHeapOccupancyPercent=35 -XX:+ExplicitGCInvokesConcurrent -XX:MaxInlineLevel=15 -Djava.awt.headless=true -Xlog:gc*:file=/usr/local/kafka/bin/../logs/zookeeper-gc.log:time,tags:filecount=10,filesize=100M -Dcom.sun.management.jmxremote=true -Dcom.sun.management.jmxremote.authenticate=false -Dcom.sun.management.jmxremote.ssl=false -Dkafka.logs.dir=/usr/local/kafka/bin/../logs -Dlog4j.configuration=file:/usr/local/kafka/bin/../config/log4j.properties -cp /usr/local/kafka/bin/../libs/activation-1.1.1.jar:/usr/local/kafka/bin/../libs/aopalliance-repackaged-2.6.1.jar:/usr/local/kafka/bin/../libs/argparse4j-0.7.0.jar:/usr/local/kafka/bin/../libs/audience-annotations-0.12.0.jar:/usr/local/kafka/bin/../libs/caffeine-2.9.3.jar:/usr/local/kafka/bin/../libs/checker-qual-3.19.0.jar:/usr/local/kafka/bin/../libs/commons-beanutils-1.9.4.jar:/usr/local/kafka/bin/../libs/commons-cli-1.4.jar:/usr/local/kafka/bin/../libs/commons-collections-3.2.2.jar:/usr/local/kafka/bin/../libs/commons-digester-2.1.jar:/usr/local/kafka/bin/../libs/commons-io-2.11.0.jar:/usr/local/kafka/bin/../libs/commons-lang3-3.12.0.jar:/usr/local/kafka/bin/../libs/commons-logging-1.2.jar:/usr/local/kafka/bin/../libs/commons-validator-1.7.jar:/usr/local/kafka/bin/../libs/connect-api-3.8.0.jar:/usr/local/kafka/bin/../libs/connect-basic-auth-extension-3.8.0.jar:/usr/local/kafka/bin/../libs/connect-json-3.8.0.jar:/usr/local/kafka/bin/../libs/connect-mirror-3.8.0.jar:/usr/local/kafka/bin/../libs/connect-mirror-client-3.8.0.jar:/usr/local/kafka/bin/../libs/connect-runtime-3.8.0.jar:/usr/local/kafka/bin/../libs/connect-transforms-3.8.0.jar:/usr/local/kafka/bin/../libs/error_prone_annotations-2.10.0.jar:/usr/local/kafka/bin/../libs/hk2-api-2.6.1.jar:/usr/local/kafka/bin/../libs/hk2-locator-2.6.1.jar:/usr/local/kafka/bin/../libs/hk2-utils-2.6.1.jar:/usr/local/kafka/bin/../libs/jackson-annotations-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-core-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-databind-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-dataformat-csv-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-datatype-jdk8-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-jaxrs-base-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-jaxrs-json-provider-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-module-afterburner-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-module-jaxb-annotations-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-module-scala_2.13-2.16.2.jar:/usr/local/kafka/bin/../libs/jakarta.activation-api-1.2.2.jar:/usr/local/kafka/bin/../libs/jakarta.annotation-api-1.3.5.jar:/usr/local/kafka/bin/../libs/jakarta.inject-2.6.1.jar:/usr/local/kafka/bin/../libs/jakarta.validation-api-2.0.2.jar:/usr/local/kafka/bin/../libs/jakarta.ws.rs-api-2.1.6.jar:/usr/local/kafka/bin/../libs/jakarta.xml.bind-api-2.3.3.jar:/usr/local/kafka/bin/../libs/javassist-3.29.2-GA.jar:/usr/local/kafka/bin/../libs/javax.activation-api-1.2.0.jar:/usr/local/kafka/bin/../libs/javax.annotation-api-1.3.2.jar:/usr/local/kafka/bin/../libs/javax.servlet-api-3.1.0.jar:/usr/local/kafka/bin/../libs/javax.ws.rs-api-2.1.1.jar:/usr/local/kafka/bin/../libs/jaxb-api-2.3.1.jar:/usr/local/kafka/bin/../libs/jersey-client-2.39.1.jar:/usr/local/kafka/bin/../libs/jersey-common-2.39.1.jar:/usr/local/kafka/bin/../libs/jersey-container-servlet-2.39.1.jar:/usr/local/kafka/bin/../libs/jersey-container-servlet-core-2.39.1.jar:/usr/local/kafka/bin/../libs/jersey-hk2-2.39.1.jar:/usr/local/kafka/bin/../libs/jersey-server-2.39.1.jar:/usr/local/kafka/bin/../libs/jetty-client-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-continuation-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-http-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-io-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-security-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-server-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-servlet-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-servlets-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-util-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-util-ajax-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jline-3.25.1.jar:/usr/local/kafka/bin/../libs/jopt-simple-5.0.4.jar:/usr/local/kafka/bin/../libs/jose4j-0.9.4.jar:/usr/local/kafka/bin/../libs/jsr305-3.0.2.jar:/usr/local/kafka/bin/../libs/kafka_2.13-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-clients-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-group-coordinator-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-group-coordinator-api-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-log4j-appender-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-metadata-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-raft-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-server-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-server-common-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-shell-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-storage-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-storage-api-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-streams-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-streams-examples-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-streams-scala_2.13-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-streams-test-utils-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-tools-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-tools-api-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-transaction-coordinator-3.8.0.jar:/usr/local/kafka/bin/../libs/lz4-java-1.8.0.jar:/usr/local/kafka/bin/../libs/maven-artifact-3.9.6.jar:/usr/local/kafka/bin/../libs/metrics-core-2.2.0.jar:/usr/local/kafka/bin/../libs/metrics-core-4.1.12.1.jar:/usr/local/kafka/bin/../libs/netty-buffer-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-codec-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-common-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-handler-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-resolver-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-transport-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-transport-classes-epoll-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-transport-native-epoll-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-transport-native-unix-common-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/opentelemetry-proto-1.0.0-alpha.jar:/usr/local/kafka/bin/../libs/osgi-resource-locator-1.0.3.jar:/usr/local/kafka/bin/../libs/paranamer-2.8.jar:/usr/local/kafka/bin/../libs/pcollections-4.0.1.jar:/usr/local/kafka/bin/../libs/plexus-utils-3.5.1.jar:/usr/local/kafka/bin/../libs/protobuf-java-3.23.4.jar:/usr/local/kafka/bin/../libs/reflections-0.10.2.jar:/usr/local/kafka/bin/../libs/reload4j-1.2.25.jar:/usr/local/kafka/bin/../libs/rocksdbjni-7.9.2.jar:/usr/local/kafka/bin/../libs/scala-collection-compat_2.13-2.10.0.jar:/usr/local/kafka/bin/../libs/scala-java8-compat_2.13-1.0.2.jar:/usr/local/kafka/bin/../libs/scala-library-2.13.14.jar:/usr/local/kafka/bin/../libs/scala-logging_2.13-3.9.4.jar:/usr/local/kafka/bin/../libs/scala-reflect-2.13.14.jar:/usr/local/kafka/bin/../libs/slf4j-api-1.7.36.jar:/usr/local/kafka/bin/../libs/slf4j-reload4j-1.7.36.jar:/usr/local/kafka/bin/../libs/snappy-java-1.1.10.5.jar:/usr/local/kafka/bin/../libs/swagger-annotations-2.2.8.jar:/usr/local/kafka/bin/../libs/trogdor-3.8.0.jar:/usr/local/kafka/bin/../libs/zookeeper-3.8.4.jar:/usr/local/kafka/bin/../libs/zookeeper-jute-3.8.4.jar:/usr/local/kafka/bin/../libs/zstd-jni-1.5.6-3.jar org.apache.zookeeper.server.quorum.QuorumPeerMain /usr/local/kafka/config/zookeeper.properties
  16374       1 root      0.1  0.6 356996 Ssl /opt/scanengine/scanengine_bitdefender -d -c /opt/mnx/etc/mnx_config.json
  16936       1 root      0.0  0.7 380240 Sl  python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16937   16936 root      0.0  0.7 378520 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16938   16936 root      0.0  0.7 378520 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16939   16936 root      0.0  0.7 378520 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16940   16936 root      0.0  0.7 378520 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16941   16936 root      0.0  0.7 378520 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16942   16936 root      0.0  0.7 378520 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16943   16936 root      0.0  0.7 378536 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16947   16936 root      0.0  0.7 378536 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16949   16936 root      0.0  0.7 378584 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16959   16936 root      0.0  0.7 378584 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16962   16936 root      0.0  0.7 378520 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16972   16936 root      0.0  0.7 378520 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16974   16936 root      0.0  0.7 378520 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16975   16936 root      0.0  0.7 378520 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16976   16936 root      0.0  0.7 378520 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  16977   16936 root      0.0  0.7 378520 S   python3.12 /opt/file_analysis_ai/file_analysis_ai.py --config /opt/mnx/etc/mnx_config.json start
  17016       1 root      1.1  0.8 412336 Ssl /usr/share/elasticsearch/jdk//bin/java -Xmx1G -Xms1G -server -XX:+UseG1GC -XX:MaxGCPauseMillis=20 -XX:InitiatingHeapOccupancyPercent=35 -XX:+ExplicitGCInvokesConcurrent -XX:MaxInlineLevel=15 -Djava.awt.headless=true -Xlog:gc*:file=/usr/local/kafka/bin/../logs/kafkaServer-gc.log:time,tags:filecount=10,filesize=100M -Dcom.sun.management.jmxremote=true -Dcom.sun.management.jmxremote.authenticate=false -Dcom.sun.management.jmxremote.ssl=false -Dkafka.logs.dir=/usr/local/kafka/bin/../logs -Dlog4j.configuration=file:/usr/local/kafka/bin/../config/log4j.properties -cp /usr/local/kafka/bin/../libs/activation-1.1.1.jar:/usr/local/kafka/bin/../libs/aopalliance-repackaged-2.6.1.jar:/usr/local/kafka/bin/../libs/argparse4j-0.7.0.jar:/usr/local/kafka/bin/../libs/audience-annotations-0.12.0.jar:/usr/local/kafka/bin/../libs/caffeine-2.9.3.jar:/usr/local/kafka/bin/../libs/checker-qual-3.19.0.jar:/usr/local/kafka/bin/../libs/commons-beanutils-1.9.4.jar:/usr/local/kafka/bin/../libs/commons-cli-1.4.jar:/usr/local/kafka/bin/../libs/commons-collections-3.2.2.jar:/usr/local/kafka/bin/../libs/commons-digester-2.1.jar:/usr/local/kafka/bin/../libs/commons-io-2.11.0.jar:/usr/local/kafka/bin/../libs/commons-lang3-3.12.0.jar:/usr/local/kafka/bin/../libs/commons-logging-1.2.jar:/usr/local/kafka/bin/../libs/commons-validator-1.7.jar:/usr/local/kafka/bin/../libs/connect-api-3.8.0.jar:/usr/local/kafka/bin/../libs/connect-basic-auth-extension-3.8.0.jar:/usr/local/kafka/bin/../libs/connect-json-3.8.0.jar:/usr/local/kafka/bin/../libs/connect-mirror-3.8.0.jar:/usr/local/kafka/bin/../libs/connect-mirror-client-3.8.0.jar:/usr/local/kafka/bin/../libs/connect-runtime-3.8.0.jar:/usr/local/kafka/bin/../libs/connect-transforms-3.8.0.jar:/usr/local/kafka/bin/../libs/error_prone_annotations-2.10.0.jar:/usr/local/kafka/bin/../libs/hk2-api-2.6.1.jar:/usr/local/kafka/bin/../libs/hk2-locator-2.6.1.jar:/usr/local/kafka/bin/../libs/hk2-utils-2.6.1.jar:/usr/local/kafka/bin/../libs/jackson-annotations-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-core-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-databind-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-dataformat-csv-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-datatype-jdk8-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-jaxrs-base-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-jaxrs-json-provider-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-module-afterburner-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-module-jaxb-annotations-2.16.2.jar:/usr/local/kafka/bin/../libs/jackson-module-scala_2.13-2.16.2.jar:/usr/local/kafka/bin/../libs/jakarta.activation-api-1.2.2.jar:/usr/local/kafka/bin/../libs/jakarta.annotation-api-1.3.5.jar:/usr/local/kafka/bin/../libs/jakarta.inject-2.6.1.jar:/usr/local/kafka/bin/../libs/jakarta.validation-api-2.0.2.jar:/usr/local/kafka/bin/../libs/jakarta.ws.rs-api-2.1.6.jar:/usr/local/kafka/bin/../libs/jakarta.xml.bind-api-2.3.3.jar:/usr/local/kafka/bin/../libs/javassist-3.29.2-GA.jar:/usr/local/kafka/bin/../libs/javax.activation-api-1.2.0.jar:/usr/local/kafka/bin/../libs/javax.annotation-api-1.3.2.jar:/usr/local/kafka/bin/../libs/javax.servlet-api-3.1.0.jar:/usr/local/kafka/bin/../libs/javax.ws.rs-api-2.1.1.jar:/usr/local/kafka/bin/../libs/jaxb-api-2.3.1.jar:/usr/local/kafka/bin/../libs/jersey-client-2.39.1.jar:/usr/local/kafka/bin/../libs/jersey-common-2.39.1.jar:/usr/local/kafka/bin/../libs/jersey-container-servlet-2.39.1.jar:/usr/local/kafka/bin/../libs/jersey-container-servlet-core-2.39.1.jar:/usr/local/kafka/bin/../libs/jersey-hk2-2.39.1.jar:/usr/local/kafka/bin/../libs/jersey-server-2.39.1.jar:/usr/local/kafka/bin/../libs/jetty-client-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-continuation-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-http-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-io-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-security-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-server-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-servlet-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-servlets-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-util-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jetty-util-ajax-9.4.54.v20240208.jar:/usr/local/kafka/bin/../libs/jline-3.25.1.jar:/usr/local/kafka/bin/../libs/jopt-simple-5.0.4.jar:/usr/local/kafka/bin/../libs/jose4j-0.9.4.jar:/usr/local/kafka/bin/../libs/jsr305-3.0.2.jar:/usr/local/kafka/bin/../libs/kafka_2.13-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-clients-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-group-coordinator-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-group-coordinator-api-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-log4j-appender-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-metadata-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-raft-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-server-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-server-common-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-shell-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-storage-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-storage-api-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-streams-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-streams-examples-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-streams-scala_2.13-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-streams-test-utils-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-tools-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-tools-api-3.8.0.jar:/usr/local/kafka/bin/../libs/kafka-transaction-coordinator-3.8.0.jar:/usr/local/kafka/bin/../libs/lz4-java-1.8.0.jar:/usr/local/kafka/bin/../libs/maven-artifact-3.9.6.jar:/usr/local/kafka/bin/../libs/metrics-core-2.2.0.jar:/usr/local/kafka/bin/../libs/metrics-core-4.1.12.1.jar:/usr/local/kafka/bin/../libs/netty-buffer-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-codec-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-common-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-handler-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-resolver-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-transport-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-transport-classes-epoll-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-transport-native-epoll-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/netty-transport-native-unix-common-4.1.110.Final.jar:/usr/local/kafka/bin/../libs/opentelemetry-proto-1.0.0-alpha.jar:/usr/local/kafka/bin/../libs/osgi-resource-locator-1.0.3.jar:/usr/local/kafka/bin/../libs/paranamer-2.8.jar:/usr/local/kafka/bin/../libs/pcollections-4.0.1.jar:/usr/local/kafka/bin/../libs/plexus-utils-3.5.1.jar:/usr/local/kafka/bin/../libs/protobuf-java-3.23.4.jar:/usr/local/kafka/bin/../libs/reflections-0.10.2.jar:/usr/local/kafka/bin/../libs/reload4j-1.2.25.jar:/usr/local/kafka/bin/../libs/rocksdbjni-7.9.2.jar:/usr/local/kafka/bin/../libs/scala-collection-compat_2.13-2.10.0.jar:/usr/local/kafka/bin/../libs/scala-java8-compat_2.13-1.0.2.jar:/usr/local/kafka/bin/../libs/scala-library-2.13.14.jar:/usr/local/kafka/bin/../libs/scala-logging_2.13-3.9.4.jar:/usr/local/kafka/bin/../libs/scala-reflect-2.13.14.jar:/usr/local/kafka/bin/../libs/slf4j-api-1.7.36.jar:/usr/local/kafka/bin/../libs/slf4j-reload4j-1.7.36.jar:/usr/local/kafka/bin/../libs/snappy-java-1.1.10.5.jar:/usr/local/kafka/bin/../libs/swagger-annotations-2.2.8.jar:/usr/local/kafka/bin/../libs/trogdor-3.8.0.jar:/usr/local/kafka/bin/../libs/zookeeper-3.8.4.jar:/usr/local/kafka/bin/../libs/zookeeper-jute-3.8.4.jar:/usr/local/kafka/bin/../libs/zstd-jni-1.5.6-3.jar kafka.Kafka /usr/local/kafka/config/server.properties
  17833       1 root      0.2  0.0 12540 Ssl  /opt/payload_analysis/payload_analysis -d -c /opt/mnx/etc/mnx_config.json
  18076       1 root     12.1 17.0 8775244 Ssl /opt/mnxdpi/mnxdpi -c /opt/mnx/etc/mnx_config.json -s
  18352       1 root      0.0  0.0   960 Ss   /bin/sh -c /opt/mnx/bin/capture -c /opt/mnx/etc/config.ini  >> /logs/mnxcapture/capture.log 2>&1
  18353   18352 nobody   31.0  2.2 1180308 RL /opt/mnx/bin/capture -c /opt/mnx/etc/config.ini
  18585       1 suricata  6.3  0.6 350104 Ssl /usr/bin/suricata --af-packet -c /etc/suricata/suricata.yaml --pidfile /run/suricata.pid --user suricata --group suricata
  18814       1 root      0.0  0.0 23660 Ss   python3.12 /opt/regression_api/app.py /opt/mnx/etc/mnx_config.json
  18900   18814 root      0.0  0.0 16436 S    python3.12 /opt/regression_api/app.py /opt/mnx/etc/mnx_config.json
  18901   18814 root      0.0  0.0 16436 S    python3.12 /opt/regression_api/app.py /opt/mnx/etc/mnx_config.json
  18902   18814 root      0.0  0.0 16440 S    python3.12 /opt/regression_api/app.py /opt/mnx/etc/mnx_config.json
  18903   18814 root      0.0  0.0 16440 S    python3.12 /opt/regression_api/app.py /opt/mnx/etc/mnx_config.json
  18906   18814 root      0.0  0.0 16448 S    python3.12 /opt/regression_api/app.py /opt/mnx/etc/mnx_config.json
  23570   23566 root      0.2  0.2 121584 Sl  /root/.vscode-server/cli/servers/Stable-7e7950df89d055b5a378379db9ee14290772148a/server/node /root/.vscode-server/cli/servers/Stable-7e7950df89d055b5a378379db9ee14290772148a/server/out/server-main.js --connection-token=remotessh --accept-server-license-terms --agent-host-bridge-port=22881 --agent-host-bridge-host=127.0.0.1 --agent-host-bridge-connection-token=c11bd8f4-8943-4b66-9ecc-fc13fb8858a2 --start-server --enable-remote-auto-shutdown --socket-path=/tmp/code-aaf6d161-17e4-4cde-a399-fec746a21ebb
  23599   23570 root      0.0  0.1 54516 Sl   /root/.vscode-server/cli/servers/Stable-7e7950df89d055b5a378379db9ee14290772148a/server/node /root/.vscode-server/cli/servers/Stable-7e7950df89d055b5a378379db9ee14290772148a/server/out/bootstrap-fork --type=fileWatcher
  23619   23570 root      0.4  0.8 420588 Sl  /root/.vscode-server/cli/servers/Stable-7e7950df89d055b5a378379db9ee14290772148a/server/node --dns-result-order=ipv4first /root/.vscode-server/cli/servers/Stable-7e7950df89d055b5a378379db9ee14290772148a/server/out/bootstrap-fork --type=extensionHost --transformURIs --useHostProxy=false
  23645   23570 root      0.1  0.1 72156 Sl   /root/.vscode-server/cli/servers/Stable-7e7950df89d055b5a378379db9ee14290772148a/server/node /root/.vscode-server/cli/servers/Stable-7e7950df89d055b5a378379db9ee14290772148a/server/out/bootstrap-fork --type=ptyHost --logsPath /root/.vscode-server/data/logs/20260710T101343
  63670   63666 root      0.0  0.0   992 Ss   /bin/sh -c sleep 30; /usr/bin/python3.12 /opt/server_check/server_check.py --cpu_interval 5 --hdd_path /data
  66631   63670 root      0.0  0.0 33060 S    /usr/bin/python3.12 /opt/server_check/server_check.py --cpu_interval 5 --hdd_path /data
```

## docker ps + networks
```
CONTAINER ID   IMAGE                   COMMAND                  CREATED        STATUS          PORTS     NAMES
8e17ecc7c9b7   mnx-api-v23:v23.5.1.2   "/__cacert_entrypoin…"   2 months ago   Up 37 minutes             mnx_api_server
2beb10e5664c   mnx-web-v23:v23.5.1.2   "/entrypoint.sh --tr…"   2 months ago   Up 37 minutes             mnx_web_server

NETWORK ID     NAME      DRIVER    SCOPE
4aee3def8f8c   bridge    bridge    local
27f94ae3b99d   host      host      local
7b97563eb12b   none      null      local

/mnx_api_server invalid IP ports=map[]
/mnx_web_server invalid IP ports=map[]
```

## 분석가 교차 확인 노트 (근거 기반)
- **포트 8000** 소유자는 `/opt/regression_api/app.py` (python3.12 pid 18814, prefork 워커 5개). NOT 관리 콘솔.
- **포트 44114** 소유자는 VSCode 원격 확장 호스트 node (pid 23619). **MNX 서비스 아님** — 문서에서 MNX 포트로 오인 금지.
- **포트 8443 = java (pid 2294)**: 정체 추정 필요(웹/API 컨테이너 또는 기타). 도커는 **host 네트워크** 사용(`docker network=host`, PortBindings 비어있음) → 컨테이너 프로세스가 호스트 포트에 직접 바인딩.
- **service_control 오케스트레이션 가설(강한 근거)**: `mnxdpi`,`mnx_payload_ai`,`mnx_payload_scan`,`kafka`,`zookeeper`는 `systemctl is-enabled=disabled`(부팅 시 미기동)이나 실제 `is-active=active`. 즉 부팅 자동기동이 아니라 **service_control(-d) 또는 수동/기타 메커니즘이 기동**. service_control 소스에서 확정할 것.
- **capture**: 부모 `sh -c` 래퍼(pid 18352) → 실제 `capture`(pid 18353)는 **user=nobody**, RUNNING(R), CPU~31%.
- **mnxdpi**: pid 18076, RSS 17%/VSZ 8.7GB, CPU~12% — 활성. "disabled"임에도 실행 중.
- **file_analysis_ai**: 마스터(16936) + 워커 ~16개 (fork 모델). 활성.
- **regression_api / server_check / suricata / payload_analysis / scanengine_bitdefender**: 모두 활성 확인.
- **디스크 압박**: `/application` 91%(19G/20G), `/data` 77%(raw pcap 31G가 대부분). 성능·장애 Phase에서 다룰 것.
- **mnxmc 콘솔**: `/mnxmc/main-login.py` (pid 4020, STAT=Ssl+, TTY foreground) 실행 중 — 대화형 관리 TUI로 추정.
