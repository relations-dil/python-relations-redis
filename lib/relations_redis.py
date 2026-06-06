"""
relations Source for Redis

A key-value Source: each record is one Redis string key holding the record's
JSON. It is the persistent twin of relations.unittest.MockSource — same model
contract (create/retrieve/update/delete via record-level matching), but the
in-memory dicts are swapped for Redis keys:

    MockSource.data[NAME][id] = values   ->   SET  <prefix>:<name>:<id> <json>
    MockSource.ids[NAME] += 1            ->   INCR <prefix>:<name>:_id

Because Redis has no query engine, only an id point-lookup can be pushed down
(GET); every other filter is a client-side scan + record.retrieve() match, exactly
as MockSource filters its in-memory values.
"""

# pylint: disable=too-many-public-methods,unused-argument,no-self-use,arguments-differ,invalid-name

import copy
import json

import redis
import overscore

import relations


class Source(relations.Source):
    """
    Redis Source
    """

    KIND = "redis"

    prefix = None       # namespace so multiple apps/tenants can share one Redis
    connection = None   # redis.Redis client

    def __init__(self, name, host="localhost", port=6379, prefix="", **kwargs):

        self.prefix = prefix
        self.connection = redis.Redis(host=host, port=port, encoding="utf-8", decode_responses=True)

    # Key helpers -- three segments, empty segments dropped so prefix="" is clean

    def _store_key(self, store):
        """
        The key prefix for a model's records: <prefix>:<store>
        """

        return ":".join(part for part in [self.prefix, store] if part != "")

    def _id_key(self, store):
        """
        The atomic id counter key for a model: <prefix>:<store>:_id
        """

        return f"{self._store_key(store)}:_id"

    def _record_key(self, store, id):
        """
        The key for a single record: <prefix>:<store>:<id>
        """

        return f"{self._store_key(store)}:{id}"

    def init(self, model):
        """
        Init the model -- mark the id field auto so create allocates it
        """

        self.record_init(model._fields)

        if model._id is not None and model._fields._names[model._id].auto is None:
            model._fields._names[model._id].auto = True

    @staticmethod
    def extract(model, values):
        """
        Extracts virtual (extract) fields from stored fields into values,
        mirroring MockSource so the stored shape is identical across backends
        """

        for extracting in [field for field in model._fields._order if field.extract]:
            for extract in extracting.extract:
                values[f"{extracting.store}__{extract}"] = overscore.get(values.get(extracting.store), extract)

        return values

    class UniqueError(relations.model.ModelError):
        """
        Exception for violating unique constraints
        """

    def uniques(self, model, values, id):
        """
        Checks unique constraints by scanning the model's existing records.

        Redis has no native unique index, so (mirroring MockSource's semantics) we serialize each
        unique field-set and compare against every other stored record. Called BEFORE the write, so
        a violating record never persists -- Redis can't cheaply snapshot/rollback like MockSource.
        """

        for unique, fields in model._unique.items():

            value = json.dumps({field: overscore.get(values, field) for field in fields}, sort_keys=True)

            for id_other, record in self._items(model.NAME):
                if str(id_other) != str(id):
                    existing = json.dumps({field: overscore.get(record, field) for field in fields}, sort_keys=True)
                    if existing == value:
                        raise self.UniqueError(model, f"value {value} violates unique {unique}")

    def create(self, model):
        """
        Executes the create -- INCR an id, then SET the record's JSON
        """

        super().create(model)

        for creating in model._each("create"):

            values = creating._record.create({})

            new_id = self.connection.incr(self._id_key(model.NAME))

            if model._id is not None and values.get(model._id) is None:
                values[model._fields._names[model._id].store] = new_id
                creating[model._id] = new_id

            self.uniques(creating, values, new_id)

            self.connection.set(self._record_key(model.NAME, new_id), json.dumps(self.extract(creating, values)))

            if not model._bulk:

                if model._id:
                    self.create_ties(creating)

                for parent_child_attr in creating.CHILDREN:
                    if creating._children.get(parent_child_attr):
                        creating._children[parent_child_attr].create()

                creating._action = "update"
                creating._record._action = "update"

        if model._bulk:
            model._models = []
        else:
            model._action = "update"

        return model

    def _records(self, name):
        """
        Reads every stored record for a model out of Redis (skipping the id counter)
        """

        return [values for _, values in self._items(name)]

    def _items(self, name):
        """
        Reads every stored record for a model as (id, values) pairs (skipping the id counter).

        Sorted by id ascending: Redis SCAN returns keys in no guaranteed order, so we sort to
        match MockSource's deterministic base order (it iterates its dict in insertion = id order).
        Without this, any unsorted retrieve (e.g. titles) is non-deterministic across Redis instances.
        """

        prefix = self._store_key(name)

        items = [
            (key.rsplit(":", 1)[-1], json.loads(self.connection.get(key)))
            for key in self.connection.scan_iter(match=f"{prefix}:*")
            if not key.endswith(":_id")
        ]

        return sorted(items, key=lambda item: int(item[0]))

    def model_like(self, model):
        """
        Gets the like matching records
        """

        parents = {}

        for field in model._titles:
            relation = model._ancestor(field)
            if relation:
                parent = relation.Parent.many(like=model._like).limit(model._chunk)
                parents[model._fields._names[field].store] = parent[relation.parent_id]
                model.overflow = model.overflow or parent.overflow

        likes = []

        for record in self._records(model.NAME):
            if model._record.like(record, model._titles, model._like, parents):
                likes.append(record)

        return likes

    @staticmethod
    def model_sort(model):
        """
        Sorts the results
        """

        sort = model._sort or model._order

        if sort:
            model.sort(*sort)._sort = None

    @staticmethod
    def model_limit(model):
        """
        Limits the results
        """

        if model._limit is None:
            return

        model._models = model._models[model._offset:model._offset + model._limit]
        model.overflow = model.overflow or len(model._models) >= model._limit

    def retrieve(self, model, verify=True):
        """
        Executes the retrieve -- scan the model's keys and match each in Python
        """

        super().retrieve(model)

        model._collate()

        records = self.model_like(model) if model._like is not None else self._records(model.NAME)

        matches = []

        for record in records:
            if model._record.retrieve(record):
                matches.append(record)

        if model._mode == "one" and len(matches) > 1:
            raise relations.model.ModelError(model, "more than one retrieved")

        if model._mode == "one" and model._role != "child":

            if len(matches) < 1:

                if verify:
                    raise relations.model.ModelError(model, "none retrieved")

                return None

            model._record = model._build("update", _read=matches[0])

        else:

            model._models = []

            for match in matches:
                model._models.append(model.__class__(_read=match))

            model._record = None

        model._action = "update"

        if model._mode == "many":
            self.model_sort(model)
            self.model_limit(model)

        self.retrieve_ties(model)

        return model

    def count(self, model):
        """
        Executes the count -- scan the model's keys and tally Python-side matches
        """

        super().count(model)

        model._collate()

        records = self.model_like(model) if model._like is not None else self._records(model.NAME)

        matches = 0

        for record in records:
            if model._record.retrieve(record):
                matches += 1

        return matches

    def titles(self, model):
        """
        Creates the titles structure
        """

        super().titles(model)

        if model._action == "retrieve":
            self.retrieve(model)

        titles = relations.Titles(model)

        for titling in model._each():
            titles.add(titling)

        return titles

    def update(self, model):
        """
        Executes the update -- GET-merge-SET (Redis stores whole JSON blobs, no partial column update)
        """

        updated = 0

        # The overall model is retrieving and the record has values set (mass update)

        if model._action == "retrieve" and model._record._action == "update":

            values = model._record.mass({})
            ties = model._record.tie({})

            for id, data in self._items(model.NAME):

                if model._record.retrieve(data):
                    updated += 1
                    updating = {**data, **values}
                    self.uniques(model, updating, id)
                    data.update(self.extract(model, copy.deepcopy(values)))
                    self.connection.set(self._record_key(model.NAME, id), json.dumps(data))
                    self.delete_ties(model, updating[model._id] if model._id else id)
                    self.create_ties(model, {**updating, **ties})

        elif model._id:

            for updating in model._each("update"):

                data = self.extract(updating, updating._record.update({}))
                key = self._record_key(model.NAME, updating[model._id])
                stored = json.loads(self.connection.get(key))
                stored.update(data)
                self.uniques(updating, stored, updating[model._id])
                self.connection.set(key, json.dumps(stored))

                self.delete_ties(updating)
                self.create_ties(updating)

                updated += 1

                for parent_child_attr in updating.CHILDREN:
                    if updating._children.get(parent_child_attr):
                        updating._children[parent_child_attr].create().update()

        else:

            raise relations.model.ModelError(model, "nothing to update from")

        return updated

    def delete(self, model):
        """
        Executes the delete -- DEL the matching keys
        """

        ids = []

        if model._action == "retrieve":

            for id, record in self._items(model.NAME):
                if model._record.retrieve(record):
                    ids.append(id)

        elif model._id:

            for deleting in model._each():
                ids.append(deleting[model._id])
                deleting._action = "create"

            model._action = "create"

        else:

            raise relations.model.ModelError(model, "nothing to delete from")

        for id in ids:
            self.connection.delete(self._record_key(model.NAME, id))
            self.delete_ties(model, id)

        return len(ids)
