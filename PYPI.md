# relations-redis

DB/API Modeling for Redis

Relations overall is designed to be a simple, straight forward, flexible DIL (data interface layer).

Quite different from other DIL's, it has the singular, microservice based purpose to:
- Create models with very little code, independent of backends
- Create CRUD API with a database backend from those models with very little code
- Create microservices to use those same models but with that CRUD API as the backend

Ya, that last one is kinda new I guess.

Say we create a service, composed of microservices, which in turn is to be consumed by other services made of microservices.

You should only need to define the model once. Your conceptual structure is the same, to the DB, the API, and anything using that API. You shouldn't have say that structure over and over. You shouldn't have to define CRUD endpoints over and over. That's so boring, tedious, and unnecessary.

Furthermore, the conceptual structure is based not the backend of what you've going to use at that moment of time (scaling matters) but on the relations, how the pieces interact. If you know the structure of the data, that's all you need to interact with the data.

So with Relations, Models and Fields are defined independent of any backend, which instead is set at runtime. So the API will use a DB, everything else will use that API.

This is just the Redis backend of models and what not.

Unlike the SQL backends, Redis is a key-value store with no query engine. Each record is
stored as one JSON string keyed by `<prefix>:<model>:<id>`, with an atomic `INCR` counter
allocating ids. Id-based reads/writes/deletes are direct `GET`/`SET`/`DEL`; any other filter
is resolved client-side by scanning the model's keys and matching in Python (the same record
matcher every backend uses) — so the model-facing API is identical, but a non-id filter is a
full scan rather than an indexed query.

Don't have great docs yet so I've included some of the unittests to show what's possible.

# Example

## define

```python

import relations
import relations_redis

# The source is a string, the backend of which is defined at runtime

class SourceModel(relations.Model):
    SOURCE = "RedisSource"

class Simple(SourceModel):
    id = int
    name = str

class Plain(SourceModel):
    ID = None # This table has no primary id field
    simple_id = int
    name = str

# This makes Simple a parent of Plain

relations.OneToMany(Simple, Plain)

# With this statement, all the above models now have this Redis as a backend.
# Redis is schemaless, so there's no define()/migrate() step — just connect.

self.source = relations_redis.Source("RedisSource", host="localhost", port=6379)
```

## create

```python
simple = Simple("sure")
simple.plain.add("fine")

simple.create()

self.assertEqual(simple.id, 1)
self.assertEqual(simple._action, "update")
self.assertEqual(simple._record._action, "update")
self.assertEqual(simple.plain[0].simple_id, 1)
self.assertEqual(simple.plain._action, "update")
self.assertEqual(simple.plain[0]._record._action, "update")

# Each record is one JSON string keyed by <prefix>:<model>:<id>

self.assertEqual(
    json.loads(self.source.connection.get("simple:1")),
    {"id": 1, "name": "sure"}
)

simples = Simple.bulk().add("ya").create()
self.assertEqual(simples._models, [])

self.assertEqual(
    json.loads(self.source.connection.get("simple:2")),
    {"id": 2, "name": "ya"}
)

self.assertEqual(
    json.loads(self.source.connection.get("plain:1")),
    {"simple_id": 1, "name": "fine"}
)
```
