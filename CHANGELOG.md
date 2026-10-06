# Changelog

All notable changes to python-relations-redis are recorded here, newest first. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

## [0.2.3] - 2026-06-08

- Bumped the `relations-dil` requirement to 0.6.15 and installed git in the Dockerfile; tests were extended to cover searching ties through attributes.

## [0.2.1] - 2026-06-07

- Added a `VERSION` file read by `setup.py` and the Makefile, with an optional `BUILD_VERSION` override, to fix PyPI packaging.
- Corrected the egg-info entry in `.gitignore`; tests were extended to cover many-to-many ties.

## [0.2.0] - 2026-06-07

- Initial release of `relations_redis.Source`, a Redis Source that stores each record as a JSON string under a `<prefix>:<store>:<id>` key, with ids allocated by a per-model `INCR` counter and an optional `prefix`, `host` and `port`.
- Supported create, retrieve, count, titles, update and delete, with unique constraints checked before writes (raising `Source.UniqueError`), extracted fields stored like the mock source, and retrieve results sorted by id; filters other than id lookups are matched client-side by scanning records.
- Included a PyPI description, license, Dockerfile, Jenkinsfile, Makefile and a Redis test helper script.
