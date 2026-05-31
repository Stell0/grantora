#!/bin/sh
set -eu

: "${APISIX_ADMIN_KEY:?APISIX_ADMIN_KEY must be set}"

perl -pe 's/\$\{\{APISIX_ADMIN_KEY\}\}/$ENV{APISIX_ADMIN_KEY}/g' \
  /usr/local/apisix/conf/config-template.yaml > /usr/local/apisix/conf/config.yaml

exec /docker-entrypoint.sh docker-start
