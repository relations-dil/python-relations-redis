#!/bin/sh -e
nslookup "$REDIS_HOST"
while ! nc -z "$REDIS_HOST" "$REDIS_PORT"; do
  sleep 1
done
echo "Redis ready"
