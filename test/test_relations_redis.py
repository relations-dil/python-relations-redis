import unittest
import unittest.mock

import os
import json

import ipaddress

import redis

import relations
import relations_redis


class SourceModel(relations.Model):
    SOURCE = "RedisSource"

class Simple(SourceModel):
    id = int
    name = str

class Plain(SourceModel):
    ID = None
    simple_id = int
    name = str

relations.OneToMany(Simple, Plain)

class Meta(SourceModel):
    id = int
    name = str
    flag = bool
    spend = float
    people = set
    stuff = list
    things = dict, {"extract": "for__0____1"}
    push = str, {"inject": "stuff___1__relations.io____1"}

def subnet_attr(values, value):

    values["address"] = str(value)
    min_ip = value[0]
    max_ip = value[-1]
    values["min_address"] = str(min_ip)
    values["min_value"] = int(min_ip)
    values["max_address"] = str(max_ip)
    values["max_value"] = int(max_ip)

class Net(SourceModel):

    id = int
    ip = ipaddress.IPv4Address, {
        "attr": {"compressed": "address", "__int__": "value"},
        "init": "address",
        "titles": "address",
        "extract": {"address": str, "value": int}
    }
    subnet = ipaddress.IPv4Network, {
        "attr": subnet_attr,
        "init": "address",
        "titles": "address"
    }

    TITLES = "ip__address"
    INDEX = "ip__value"

class Unit(SourceModel):
    id = int
    name = str, {"format": "fancy"}

class Test(SourceModel):
    id = int
    unit_id = int
    name = str, {"format": "shmancy"}

class Case(SourceModel):
    id = int
    test_id = int
    name = str

relations.OneToMany(Unit, Test)
relations.OneToOne(Test, Case)

class Sis(SourceModel):
    id = int
    name = str
    bro_id = set

class Bro(SourceModel):
    id = int
    name = str
    sis_id = set

class SisBro(SourceModel):
    ID = None
    bro_id = int
    sis_id = int

relations.ManyToMany(Sis, Bro, SisBro)


class TestSource(unittest.TestCase):

    maxDiff = None

    def setUp(self):

        self.source = relations_redis.Source(
            "RedisSource",
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", 6379))
        )

        self.source.connection.flushdb()

    def tearDown(self):

        self.source.connection.flushdb()

    def record(self, store, id):
        """
        Read one record back out of Redis as a dict
        """

        return json.loads(self.source.connection.get(self.source._record_key(store, id)))

    def records(self, store):
        """
        Read all records for a model back out of Redis (skipping the id counter)
        """

        prefix = self.source._store_key(store)

        return [
            json.loads(self.source.connection.get(key))
            for key in sorted(self.source.connection.keys(f"{prefix}:*"))
            if not key.endswith(":_id")
        ]

    @unittest.mock.patch("relations.SOURCES", {})
    @unittest.mock.patch("redis.Redis", unittest.mock.MagicMock())
    def test___init__(self):

        source = relations_redis.Source("unit", host="db.com", port=1234, prefix="app")

        self.assertEqual(source.name, "unit")
        self.assertEqual(source.prefix, "app")
        self.assertEqual(source.connection, redis.Redis.return_value)
        self.assertEqual(relations.SOURCES["unit"], source)
        redis.Redis.assert_called_once_with(host="db.com", port=1234, encoding="utf-8", decode_responses=True)

    def test_create(self):

        simple = Simple("sure")
        simple.plain.add("fine")

        simple.create()

        self.assertEqual(simple.id, 1)
        self.assertEqual(simple._action, "update")
        self.assertEqual(simple._record._action, "update")
        self.assertEqual(simple.plain[0].simple_id, 1)
        self.assertEqual(simple.plain._action, "update")
        self.assertEqual(simple.plain[0]._record._action, "update")

        self.assertEqual(self.record("simple", 1), {"id": 1, "name": "sure"})

        simples = Simple.bulk().add("ya").create()
        self.assertEqual(simples._models, [])

        self.assertEqual(self.record("simple", 2), {"id": 2, "name": "ya"})

        self.assertEqual(self.record("plain", 1), {"simple_id": 1, "name": "fine"})

        Meta("yep", True, 3.50, {"tom", "mary"}, [1, None], {"for": [{"1": "yep"}]}, "sure").create()

        self.assertEqual(self.record("meta", 1), {
            "id": 1,
            "name": "yep",
            "flag": True,
            "spend": 3.50,
            "people": ["mary", "tom"],
            "stuff": [1, {"relations.io": {"1": "sure"}}],
            "things": {"for": [{"1": "yep"}]},
            "things__for__0____1": "yep"
        })

        sis = Sis("Sally", bro_id=[2, 3, 4], _bulk=True)
        self.assertRaisesRegex(relations.ModelError, "cannot create ties in bulk", sis.create)

        sis = Sis("Sally", bro_id=[2, 3, 4]).create()

        self.assertEqual(sorted(self.records("sis_bro"), key=lambda record: record["bro_id"]), [
            {"sis_id": sis.id, "bro_id": 2},
            {"sis_id": sis.id, "bro_id": 3},
            {"sis_id": sis.id, "bro_id": 4}
        ])

    def test_retrieve(self):

        Unit([["stuff"], ["people"]]).create()

        models = Unit.one(name__in=["people", "stuff"])
        self.assertRaisesRegex(relations.ModelError, "unit: more than one retrieved", models.retrieve)

        model = Unit.one(name="things")
        self.assertRaisesRegex(relations.ModelError, "unit: none retrieved", model.retrieve)

        self.assertIsNone(model.retrieve(False))

        unit = Unit.one(name="people")

        self.assertEqual(unit.id, 2)
        self.assertEqual(unit._action, "update")
        self.assertEqual(unit._record._action, "update")

        unit.test.add("things")[0].case.add("persons")
        unit.update()

        model = Unit.many(test__name="things")

        self.assertEqual(model.id, [2])
        self.assertEqual(model[0]._action, "update")
        self.assertEqual(model[0]._record._action, "update")
        self.assertEqual(model[0].test[0].id, 1)
        self.assertEqual(model[0].test[0].case.name, "persons")

        model = Unit.many(like="p")
        self.assertEqual(model.name, ["people"])

        model = Test.many(like="p").retrieve()
        self.assertEqual(model.name, ["things"])
        self.assertFalse(model.overflow)

        model = Test.many(like="p", _chunk=1).retrieve()
        self.assertEqual(model.name, ["things"])
        self.assertTrue(model.overflow)

        Meta("yep", True, 1.1, {"tom"}, [1, None], {"a": 1}).create()
        model = Meta.one(name="yep")

        self.assertEqual(model.flag, True)
        self.assertEqual(model.spend, 1.1)
        self.assertEqual(model.people, {"tom"})
        self.assertEqual(model.stuff, [1, {"relations.io": {"1": None}}])
        self.assertEqual(model.things, {"a": 1})

        self.assertEqual(Unit.many().name, ["people", "stuff"])
        self.assertEqual(Unit.many().sort("-name").name, ["stuff", "people"])
        self.assertEqual(Unit.many().sort("-name").limit(1, 1).name, ["people"])
        self.assertEqual(Unit.many().sort("-name").limit(0).name, [])
        self.assertEqual(Unit.many(name="people").limit(1).name, ["people"])

        Meta("dive", people={"tom", "mary"}, stuff=[1, 2, 3, None], things={"a": {"b": [1, 2], "c": "sure"}, "4": 5, "for": [{"1": "yep"}]}).create()

        model = Meta.many(people={"tom", "mary"})
        self.assertEqual(model[0].name, "dive")

        model = Meta.many(stuff=[1, 2, 3, {"relations.io": {"1": None}}])
        self.assertEqual(model[0].name, "dive")

        model = Meta.many(things={"a": {"b": [1, 2], "c": "sure"}, "4": 5, "for": [{"1": "yep"}]})
        self.assertEqual(model[0].name, "dive")

        model = Meta.many(stuff__1=2)
        self.assertEqual(model[0].name, "dive")

        model = Meta.many(things__a__b__0=1)
        self.assertEqual(model[0].name, "dive")

        model = Meta.many(things__a__c__like="su")
        self.assertEqual(model[0].name, "dive")

        model = Meta.many(things__a__d__null=True)
        self.assertEqual(model[0].name, "dive")

        model = Meta.many(things____4=5)
        self.assertEqual(model[0].name, "dive")

        model = Meta.many(things__a__b__0__gt=1)
        self.assertEqual(len(model), 0)

        model = Meta.many(things__a__c__notlike="su")
        self.assertEqual(len(model), 0)

        model = Meta.many(things__a__d__null=False)
        self.assertEqual(len(model), 0)

        model = Meta.many(things____4=6)
        self.assertEqual(len(model), 0)

        model = Meta.many(things__a__b__has=1)
        self.assertEqual(len(model), 1)

        model = Meta.many(things__a__b__has=3)
        self.assertEqual(len(model), 0)

        model = Meta.many(things__a__b__any=[1, 3])
        self.assertEqual(len(model), 1)

        model = Meta.many(things__a__b__any=[4, 3])
        self.assertEqual(len(model), 0)

        model = Meta.many(things__a__b__all=[2, 1])
        self.assertEqual(len(model), 1)

        model = Meta.many(things__a__b__all=[3, 2, 1])
        self.assertEqual(len(model), 0)

        model = Meta.many(people__has="mary")
        self.assertEqual(len(model), 1)

        model = Meta.many(people__has="dick")
        self.assertEqual(len(model), 0)

        model = Meta.many(people__any=["mary", "dick"])
        self.assertEqual(len(model), 1)

        model = Meta.many(people__any=["harry", "dick"])
        self.assertEqual(len(model), 0)

        model = Meta.many(people__all=["mary", "tom"])
        self.assertEqual(len(model), 1)

        model = Meta.many(people__all=["tom", "dick", "mary"])
        self.assertEqual(len(model), 0)

        Net(ip="1.2.3.4", subnet="1.2.3.0/24").create()
        Net().create()

        model = Net.many(like='1.2.3.')
        self.assertEqual(model[0].ip.compressed, "1.2.3.4")

        model = Net.many(ip__address__like='1.2.3.')
        self.assertEqual(model[0].ip.compressed, "1.2.3.4")

        model = Net.many(ip__value__gt=int(ipaddress.IPv4Address('1.2.3.0')))
        self.assertEqual(model[0].ip.compressed, "1.2.3.4")

        model = Net.many(subnet__address__like='1.2.3.')
        self.assertEqual(model[0].ip.compressed, "1.2.3.4")

        model = Net.many(subnet__min_value=int(ipaddress.IPv4Address('1.2.3.0')))
        self.assertEqual(model[0].ip.compressed, "1.2.3.4")

        model = Net.many(ip__address__notlike='1.2.3.')
        self.assertEqual(len(model), 0)

        model = Net.many(ip__value__lt=int(ipaddress.IPv4Address('1.2.3.0')))
        self.assertEqual(len(model), 0)

        model = Net.many(subnet__address__notlike='1.2.3.')
        self.assertEqual(len(model), 0)

        model = Net.many(subnet__max_value=int(ipaddress.IPv4Address('1.2.3.0')))
        self.assertEqual(len(model), 0)

        # ties: retrieved records carry their tie ids, and tie membership filters

        tom = Bro("Tom").create()
        dick = Bro("Dick").create()
        mary = Sis("Mary", bro_id=[tom.id, dick.id]).create()

        self.assertEqual(sorted(Sis.one(mary.id).bro.id), sorted([tom.id, dick.id]))

        self.assertEqual(Sis.many(bro_id=[tom.id])[0].name, "Mary")
        self.assertEqual(len(Sis.many(bro_id=[999])), 0)

    def test_retrieve_ties_query(self):

        tom = Bro("Tom").create()
        dick = Bro("Dick").create()
        harry = Bro("Harry").create()

        Sis("Mary", bro_id=[tom.id, dick.id]).create()
        Sis("Sue", bro_id=[tom.id]).create()
        Sis("Ann", bro_id=[dick.id, harry.id]).create()

        self.assertEqual(sorted(Sis.many(bro_id__has=tom.id).name), ["Mary", "Sue"])
        self.assertEqual(sorted(Sis.many(bro_id__any=[tom.id, harry.id]).name), ["Ann", "Mary", "Sue"])
        self.assertEqual(Sis.many(bro_id__all=[tom.id, dick.id]).name, ["Mary"])
        self.assertEqual(len(Sis.many(bro_id__all=[tom.id, harry.id])), 0)
        self.assertEqual(Sis.many(bro_id__not_has=tom.id).name, ["Ann"])
        self.assertEqual(sorted(Sis.many(bro_id__not_any=[harry.id]).name), ["Mary", "Sue"])

    def test_count(self):

        Unit([["stuff"], ["people"]]).create()

        self.assertEqual(Unit.many().count(), 2)
        self.assertEqual(Unit.many(name="people").count(), 1)
        self.assertEqual(Unit.many(like="p").count(), 1)

    def test_titles(self):

        Unit("people").create().test.add("stuff").add("things").create()

        titles = Unit.many().titles()

        self.assertEqual(titles.id, "id")
        self.assertEqual(titles.fields, ["name"])
        self.assertEqual(titles.parents, {})
        self.assertEqual(titles.format, ["fancy"])

        self.assertEqual(titles.ids, [1])
        self.assertEqual(titles.titles, {1: ["people"]})

        titles = Test.many().titles()

        self.assertEqual(titles.id, "id")
        self.assertEqual(titles.fields, ["unit_id", "name"])

        self.assertEqual(titles.parents["unit_id"].id, "id")
        self.assertEqual(titles.parents["unit_id"].fields, ["name"])
        self.assertEqual(titles.parents["unit_id"].parents, {})
        self.assertEqual(titles.parents["unit_id"].format, ["fancy"])

        self.assertEqual(titles.format, ["fancy", "shmancy"])

        self.assertEqual(titles.ids, [1, 2])
        self.assertEqual(titles.titles, {
            1: ["people", "stuff"],
            2: ["people", "things"]
        })

        Net(ip="1.2.3.4", subnet="1.2.3.0/24").create()

        self.assertEqual(Net.many().titles().titles, {
            1: ["1.2.3.4"]
        })

    def test_update(self):

        Unit([["people"], ["stuff"]]).create()

        unit = Unit.many(id=2).set(name="things")

        self.assertEqual(unit.update(), 1)

        unit = Unit.one(2)

        unit.name = "thing"
        unit.test.add("moar")

        self.assertEqual(unit.update(), 1)
        self.assertEqual(unit.name, "thing")
        self.assertEqual(unit.test[0].id, 1)
        self.assertEqual(unit.test[0].name, "moar")

        Meta("yep", True, 1.1, {"tom"}, [1, None], {"a": 1}).create()
        Meta.one(name="yep").set(flag=False, people=set(), stuff=[], things={}).update()

        model = Meta.one(name="yep")
        self.assertEqual(model.flag, False)
        self.assertEqual(model.spend, 1.1)
        self.assertEqual(model.people, set())
        self.assertEqual(model.stuff, [])
        self.assertEqual(model.things, {})

        plain = Plain.one()
        self.assertRaisesRegex(relations.ModelError, "plain: nothing to update from", plain.update)

        ping = Net(ip="1.2.3.4", subnet="1.2.3.0/24").create()
        pong = Net(ip="5.6.7.8", subnet="5.6.7.0/24").create()

        Net.many().set(subnet="9.10.11.0/24").update()

        self.assertEqual(Net.one(ping.id).subnet.compressed, "9.10.11.0/24")
        self.assertEqual(Net.one(pong.id).subnet.compressed, "9.10.11.0/24")

        Net.one(ping.id).set(ip="13.14.15.16").update()
        self.assertEqual(Net.one(ping.id).ip.compressed, "13.14.15.16")
        self.assertEqual(Net.one(pong.id).ip.compressed, "5.6.7.8")

        # ties: both the per-id and the mass (retrieve) update paths re-write ties

        tom = Bro("Tom").create()
        dick = Bro("Dick").create()
        harry = Bro("Harry").create()
        mary = Sis("Mary", bro_id=[tom.id, dick.id]).create()

        Sis.one(mary.id).set(bro_id=[dick.id, harry.id]).update()
        self.assertEqual(sorted(Sis.one(mary.id).bro.id), sorted([dick.id, harry.id]))

        Sis.many(name="Mary").set(bro_id=[tom.id]).update()
        self.assertEqual(Sis.one(mary.id).bro.id, [tom.id])

    def test_delete(self):

        unit = Unit("people")
        unit.test.add("stuff").add("things")
        unit.create()

        self.assertEqual(Test.one(id=2).delete(), 1)
        self.assertEqual(len(Test.many()), 1)

        self.assertEqual(Unit.one(1).test.delete(), 1)
        self.assertEqual(Unit.one(1).retrieve().delete(), 1)
        self.assertEqual(len(Unit.many()), 0)
        self.assertEqual(len(Test.many()), 0)

        self.assertEqual(Test.many().delete(), 0)

        plain = Plain(0, "nope").create()
        self.assertRaisesRegex(relations.ModelError, "plain: nothing to delete from", plain.delete)

        # ties: deleting a record removes its tie records too

        tom = Bro("Tom").create()
        mary = Sis("Mary", bro_id=[tom.id]).create()

        self.assertEqual(len(self.records("sis_bro")), 1)

        Sis.one(mary.id).delete()

        self.assertEqual(len(Sis.many()), 0)
        self.assertEqual(self.records("sis_bro"), [])

    def test_uniques(self):

        Simple("ya").create()

        # creating a duplicate of a unique field raises and does not persist

        self.assertRaisesRegex(
            relations_redis.Source.UniqueError,
            'simple: value {"name": "ya"} violates unique name',
            Simple("ya").create
        )

        self.assertEqual(Simple.many().name, ["ya"])

        # updating into a duplicate raises and does not persist

        Simple("sure").create()

        sure = Simple.one(name="sure")
        sure.name = "ya"

        self.assertRaisesRegex(
            relations_redis.Source.UniqueError,
            'simple: value {"name": "ya"} violates unique name',
            sure.update
        )

        self.assertEqual(sorted(Simple.many().name), ["sure", "ya"])
