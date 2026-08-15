# Mosquitto deployment configurations

## Classroom default

`config/mosquitto.conf` is the configuration mounted by the default
`docker-compose.yml`. It deliberately exposes anonymous, unencrypted MQTT on
port 1883 and WebSockets on port 9001 for a local classroom demonstration. It
must not be presented as secure or exposed to an untrusted network.

## Hardened external-deployment example

`config/mosquitto-hardened.conf`, `config/acl.hardened`, and
`../docker-compose.hardened.yml` are an opt-in deployment target. They require:

- TLS server materials at `runtime/certs/ca.crt`, `server.crt`, and `server.key`;
- a Mosquitto password file at `runtime/secrets/passwords` containing matching
  accounts for the placeholder ACL identities;
- replacement/review of the placeholder identities and topic grants;
- firewall, reverse-proxy, certificate-renewal, monitoring, backup, and secret
  management appropriate to the deployment environment.

No certificate, private key, password, or deployed security is included here.
The hardened example exposes MQTT/TLS on 8883 and WSS/TLS on 9002. Client code
must separately be configured with the matching hostname, trust chain, and
credentials. For browser clients, do not embed a durable password in publicly
served source; use a gateway or another mechanism for short-lived credentials.

Create the password file interactively, without putting passwords in shell
history:

```sh
mkdir -p mosquitto/runtime/secrets mosquitto/runtime/certs
mosquitto_passwd -c mosquitto/runtime/secrets/passwords simulator-publisher
mosquitto_passwd mosquitto/runtime/secrets/passwords dashboard-operator
mosquitto_passwd mosquitto/runtime/secrets/passwords visualization-viewer
```

After installing deployment certificates, render and start only the hardened
profile:

```sh
docker compose -f docker-compose.hardened.yml --profile hardened config
docker compose -f docker-compose.hardened.yml --profile hardened up -d
```

Do not run the classroom broker on the same public host unless its plaintext
ports are blocked from all untrusted networks.

## Configuration validation without production certificates

Mosquitto opens certificates and the password file when it loads the
configuration, so syntax validation needs disposable inputs. Generate them only
under the ignored `mosquitto/runtime/` directory, create placeholder accounts,
and run the same Mosquitto image used by Compose. These inputs validate loading;
they are not deployment credentials:

```sh
mkdir -p mosquitto/runtime/certs mosquitto/runtime/secrets
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -subj '/CN=localhost' \
  -keyout mosquitto/runtime/certs/server.key \
  -out mosquitto/runtime/certs/server.crt
cp mosquitto/runtime/certs/server.crt mosquitto/runtime/certs/ca.crt

docker run --rm -i \
  -v "$PWD/mosquitto/config/mosquitto-hardened.conf:/input/mosquitto.conf:ro" \
  -v "$PWD/mosquitto/config/acl.hardened:/input/acl.hardened:ro" \
  -v "$PWD/mosquitto/runtime/certs:/mosquitto/certs:ro" \
  -v "$PWD/mosquitto/runtime/secrets/passwords:/input/passwords:ro" \
  --entrypoint /bin/sh eclipse-mosquitto:2 -ec '\
    install -o mosquitto -g mosquitto -m 0600 /input/acl.hardened /tmp/acl.hardened; \
    install -o mosquitto -g mosquitto -m 0600 /input/passwords /tmp/passwords; \
    sed -e "s#/mosquitto/config/acl.hardened#/tmp/acl.hardened#" \
        -e "s#/run/secrets/mosquitto_passwords#/tmp/passwords#" \
        /input/mosquitto.conf > /tmp/mosquitto.conf; \
    exec su mosquitto -s /bin/sh -c "exec mosquitto -c /tmp/mosquitto.conf -v"'
```

A successful start reports listeners on ports 8883 and 9002. Stop it with
Ctrl-C, then remove `mosquitto/runtime/`. Runtime inputs are ignored by Git.
