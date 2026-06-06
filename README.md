# python-relations-redis

DB/API Modeling for Redis

The Redis Source for [Relations](https://github.com/relations-dil/python-relations). Define a
model once and run it on any backend; this one stores each record as a JSON string in Redis,
keyed by `<prefix>:<model>:<id>` with an atomic `INCR` id counter.

It is the persistent twin of core's `MockSource`: the same model contract
(create/retrieve/update/delete via record-level matching), but the in-memory dicts are swapped
for Redis keys. Because Redis has no query engine, only an id point-lookup is pushed down
(`GET`); every other filter is a client-side scan + match, exactly as `MockSource` filters its
in-memory values.

See `PYPI.md` for an overview and examples, and `test/test_relations_redis.py` for the full
behavior.
