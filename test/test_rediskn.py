from collections import namedtuple
from unittest.mock import call, patch, Mock, MagicMock

import pytest
from eventlet import sleep
from nameko.exceptions import ConfigurationError
from redis import StrictRedis

from nameko_rediskn import rediskn
from test import assert_items_equal, URI_CONFIG_KEY, REDIS_OPTIONS


TIME_SLEEP = 0.1


@pytest.fixture
def tracker():
    yield Mock()


@pytest.fixture
def create_service(container_factory, config, tracker):
    def create(**kwargs):
        class DummyService:

            name = 'dummy_service'

            @rediskn.subscribe(**kwargs)
            def handler(self, message):
                tracker.run(message)

        ServiceMeta = namedtuple('ServiceMeta', ['container'])
        container = container_factory(DummyService, config)

        container.start()
        sleep(TIME_SLEEP)
        return ServiceMeta(container)

    return create


@pytest.fixture
def create_dummy_service(create_service):
    def _create_dummy_service(**kwargs):
        return create_service(**kwargs)

    return _create_dummy_service


class TestRedisNotifierSetup:

    @pytest.fixture
    def service(self, create_dummy_service):
        return create_dummy_service(events='*', keys='*', dbs='*')

    def test_raises_if_uri_config_key_not_supplied(self, create_dummy_service):
        with pytest.raises(TypeError):
            create_dummy_service()

        with pytest.raises(TypeError):
            create_dummy_service(events='*', keys='*', dbs=[1])

    def test_raises_if_missing_arguments(self, create_dummy_service):
        with pytest.raises(ConfigurationError):
            create_dummy_service(uri_config_key=URI_CONFIG_KEY)

        with pytest.raises(ConfigurationError):
            create_dummy_service(uri_config_key=URI_CONFIG_KEY, dbs=[1])

    def test_container_stop(self, create_dummy_service):
        with patch(
            'nameko.containers.ServiceContainer.spawn_managed_thread'
        ) as spawn_managed_thread:
            thread_mock = MagicMock()
            thread_mock.kill.return_value = MagicMock()
            spawn_managed_thread.return_value = thread_mock
            service = create_dummy_service(
                uri_config_key=URI_CONFIG_KEY, events='*'
            )
            service.container.stop()

        assert thread_mock.kill.call_args_list == [call()]

        entrypoint = next(iter(service.container.entrypoints))
        assert entrypoint._thread is None
        assert entrypoint.client is None

    def test_container_kill(self, create_dummy_service):
        with patch(
            'nameko.containers.ServiceContainer.spawn_managed_thread'
        ) as spawn_managed_thread:
            thread_mock = MagicMock()
            thread_mock.kill.return_value = MagicMock()
            spawn_managed_thread.return_value = thread_mock
            service = create_dummy_service(
                uri_config_key=URI_CONFIG_KEY, events='*'
            )
            service.container.kill()

        assert thread_mock.kill.call_args_list == [call()]

        entrypoint = next(iter(service.container.entrypoints))
        assert entrypoint._thread is None
        assert entrypoint.client is None


class TestListenAll:

    @pytest.fixture
    def service(self, create_dummy_service):
        return create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, events='*', keys='*', dbs='*'
        )

    @pytest.mark.usefixtures('service')
    def test_subscribe_events(self, tracker, redis):
        assert tracker.run.call_args_list == [
            call({
                'data': 1,
                'type': 'psubscribe',
                'pattern': None,
                'channel': '__keyevent@*__:*'
            }),
            call({
                'data': 2,
                'type': 'psubscribe',
                'pattern': None,
                'channel': '__keyspace@*__:*'
            }),
        ]

    @pytest.mark.parametrize('action,args,event_type', [
        ('set', ('foo', 'bar'), 'set'),
        ('hset', ('foo', 'bar', 'baz'), 'hset'),
        ('hmset', ('foo', {'bar': 'baz'}), 'hset'),
    ])
    @pytest.mark.usefixtures('service')
    def test_simple_events(self, tracker, redis, action, args, event_type):
        method = getattr(redis, action)
        method(*args)
        sleep(TIME_SLEEP)

        key = args[0]

        assert_items_equal(
            tracker.run.call_args_list[-2:],
            [
                call({
                    'type': 'pmessage',
                    'pattern': '__keyspace@*__:*',
                    'channel': '__keyspace@0__:{}'.format(key),
                    'data': event_type,
                }),
                call({
                    'type': 'pmessage',
                    'pattern': '__keyevent@*__:*',
                    'channel': '__keyevent@0__:{}'.format(event_type),
                    'data': key,
                })
            ]
        )

    @pytest.mark.usefixtures('service')
    def test_del(self, tracker, redis):
        redis.set('foo', 'bar')
        redis.delete('foo')
        sleep(TIME_SLEEP)

        assert_items_equal(
            tracker.run.call_args_list[-2:],
            [
                call({
                    'type': 'pmessage',
                    'pattern': '__keyspace@*__:*',
                    'channel': '__keyspace@0__:foo',
                    'data': 'del',
                }),
                call({
                    'type': 'pmessage',
                    'pattern': '__keyevent@*__:*',
                    'channel': '__keyevent@0__:del',
                    'data': 'foo',
                })
            ]
        )

    @pytest.mark.parametrize('keys', [('one', ), ('one', 'two')])
    @pytest.mark.usefixtures('service')
    def test_hdel(self, tracker, redis, keys):
        redis.hmset('foo', {'one': '1', 'two': '2', 'three': '3'})
        redis.hdel('foo', *keys)
        sleep(TIME_SLEEP)

        assert_items_equal(
            tracker.run.call_args_list[-2:],
            [
                call({
                    'type': 'pmessage',
                    'pattern': '__keyspace@*__:*',
                    'channel': '__keyspace@0__:foo',
                    'data': 'hdel',
                }),
                call({
                    'type': 'pmessage',
                    'pattern': '__keyevent@*__:*',
                    'channel': '__keyevent@0__:hdel',
                    'data': 'foo',
                })
            ]
        )

    @pytest.mark.parametrize('action,ttl,wait_time', [
        ('expire', 1, 1.1),
        ('pexpire', 100, 0.2),
    ])
    @pytest.mark.usefixtures('service')
    def test_expire(self, tracker, redis, action, ttl, wait_time):
        redis.set('foo', 'bar')
        method = getattr(redis, action)
        method('foo', ttl)
        sleep(TIME_SLEEP)
        assert_items_equal(
            tracker.run.call_args_list[-2:],
            [
                call({
                    'type': 'pmessage',
                    'pattern': '__keyspace@*__:*',
                    'channel': '__keyspace@0__:foo',
                    'data': 'expire',
                }),
                call({
                    'type': 'pmessage',
                    'pattern': '__keyevent@*__:*',
                    'channel': '__keyevent@0__:expire',
                    'data': 'foo',
                })
            ]
        )

        sleep(wait_time)

        assert_items_equal(
            tracker.run.call_args_list[-2:],
            [
                call({
                    'type': 'pmessage',
                    'pattern': '__keyspace@*__:*',
                    'channel': '__keyspace@0__:foo',
                    'data': 'expired',
                }),
                call({
                    'type': 'pmessage',
                    'pattern': '__keyevent@*__:*',
                    'channel': '__keyevent@0__:expired',
                    'data': 'foo',
                })
            ]
        )


class TestListenEvents:

    def test_subscribe_events(self, create_dummy_service, tracker, redis):
        create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, events='psubscribe', dbs='*'
        )
        assert tracker.run.call_args_list == [
            call({
                'type': 'psubscribe',
                'pattern': None,
                'channel': '__keyevent@*__:psubscribe',
                'data': 1,
            })
        ]

    def test_listen_event(self, create_dummy_service, tracker, redis):
        create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, events='set', dbs='*'
        )

        redis.set('foo', 'bar')
        sleep(TIME_SLEEP)

        assert tracker.run.call_args_list[-1] == call({
            'type': 'pmessage',
            'pattern': '__keyevent@*__:set',
            'channel': '__keyevent@0__:set',
            'data': 'foo',
        })

    @pytest.mark.parametrize('events', [['set', 'hset'], ('set', 'hset')])
    def test_listen_multiple_events(
        self, create_dummy_service, tracker, redis, events
    ):
        create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, events=events, dbs='*'
        )

        redis.set('foo', 'bar')
        sleep(TIME_SLEEP)

        assert tracker.run.call_args_list[-1] == call({
            'type': 'pmessage',
            'pattern': '__keyevent@*__:set',
            'channel': '__keyevent@0__:set',
            'data': 'foo',
        })

        redis.hset('one', 'two', 'three')
        sleep(TIME_SLEEP)

        assert tracker.run.call_args_list[-1] == call({
            'type': 'pmessage',
            'pattern': '__keyevent@*__:hset',
            'channel': '__keyevent@0__:hset',
            'data': 'one',
        })

    def test_ignores_other_events(self, create_dummy_service, tracker, redis):
        create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, events='hset', dbs='*'
        )
        tracker.run.reset_mock()

        redis.set('foo', 'bar')
        sleep(TIME_SLEEP)

        assert tracker.run.call_args_list == []


class TestListenKeys:

    def test_subscribe_events(self, create_dummy_service, tracker, redis):
        create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, keys='foo', dbs='*'
        )
        assert tracker.run.call_args_list == [
            call({
                'type': 'psubscribe',
                'pattern': None,
                'channel': '__keyspace@*__:foo',
                'data': 1,
            })
        ]

    def test_listen_key(self, create_dummy_service, tracker, redis):
        create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, keys='foo', dbs='*'
        )

        redis.set('foo', 'bar')
        sleep(TIME_SLEEP)

        assert tracker.run.call_args_list[-1] == call({
            'type': 'pmessage',
            'pattern': '__keyspace@*__:foo',
            'channel': '__keyspace@0__:foo',
            'data': 'set',
        })

    @pytest.mark.parametrize('keys', [['foo', 'bar'], ('foo', 'bar')])
    def test_listen_multiple_keys(
        self, create_dummy_service, tracker, redis, keys
    ):
        create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, keys=keys, dbs='*'
        )

        redis.set('foo', '1')
        sleep(TIME_SLEEP)

        assert tracker.run.call_args_list[-1] == call({
            'type': 'pmessage',
            'pattern': '__keyspace@*__:foo',
            'channel': '__keyspace@0__:foo',
            'data': 'set',
        })

        redis.set('bar', '2')
        sleep(TIME_SLEEP)

        assert tracker.run.call_args_list[-1] == call({
            'type': 'pmessage',
            'pattern': '__keyspace@*__:bar',
            'channel': '__keyspace@0__:bar',
            'data': 'set',
        })

    def test_ignores_other_keys(self, create_dummy_service, tracker, redis):
        create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, keys='foo', dbs='*'
        )
        tracker.run.reset_mock()

        redis.set('bar', '2')
        sleep(TIME_SLEEP)

        assert tracker.run.call_args_list == []


class TestListenDB:

    @pytest.fixture
    def redis_db_1(self, redis_config):
        # url argument takes precedence over db in the url
        redis_uri = '{}?db=1'.format(
            redis_config['REDIS_URIS'][URI_CONFIG_KEY]
        )
        client = StrictRedis.from_url(redis_uri, db=1, **REDIS_OPTIONS)
        client.flushall()
        return client

    def test_subscribes_to_db_from_uri(self, create_dummy_service, tracker):
        create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, keys='*', events='*'
        )
        assert tracker.run.call_args_list == [
            call({
                'type': 'psubscribe',
                'pattern': None,
                'channel': '__keyevent@0__:*',
                'data': 1,
            }),
            call({
                'type': 'psubscribe',
                'pattern': None,
                'channel': '__keyspace@0__:*',
                'data': 2,
            }),
        ]

    def test_subscribe_events(self, create_dummy_service, tracker):
        create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, keys='*', events='*', dbs=1
        )
        assert tracker.run.call_args_list == [
            call({
                'type': 'psubscribe',
                'pattern': None,
                'channel': '__keyevent@1__:*',
                'data': 1,
            }),
            call({
                'type': 'psubscribe',
                'pattern': None,
                'channel': '__keyspace@1__:*',
                'data': 2,
            }),
        ]

    def test_listen_db(self, create_dummy_service, tracker, redis_db_1):
        create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, keys='*', events='*', dbs=1
        )

        redis_db_1.set('foo', 'bar')
        sleep(TIME_SLEEP)

        assert_items_equal(
            tracker.run.call_args_list[-2:],
            [
                call({
                    'type': 'pmessage',
                    'pattern': '__keyspace@1__:*',
                    'channel': '__keyspace@1__:foo',
                    'data': 'set',
                }),
                call({
                    'type': 'pmessage',
                    'pattern': '__keyevent@1__:*',
                    'channel': '__keyevent@1__:set',
                    'data': 'foo',
                })
            ]
        )

    def test_listen_multiple_dbs(
        self, create_dummy_service, tracker, redis, redis_db_1
    ):
        create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, keys='*', events='*', dbs=[0, 1]
        )

        redis.set('foo', '1')
        sleep(TIME_SLEEP)

        assert_items_equal(
            tracker.run.call_args_list[-2:],
            [
                call({
                    'type': 'pmessage',
                    'pattern': '__keyspace@0__:*',
                    'channel': '__keyspace@0__:foo',
                    'data': 'set',
                }),
                call({
                    'type': 'pmessage',
                    'pattern': '__keyevent@0__:*',
                    'channel': '__keyevent@0__:set',
                    'data': 'foo',
                })
            ]
        )

        redis_db_1.set('bar', '2')
        sleep(TIME_SLEEP)

        assert_items_equal(
            tracker.run.call_args_list[-2:],
            [
                call({
                    'type': 'pmessage',
                    'pattern': '__keyspace@1__:*',
                    'channel': '__keyspace@1__:bar',
                    'data': 'set',
                }),
                call({
                    'type': 'pmessage',
                    'pattern': '__keyevent@1__:*',
                    'channel': '__keyevent@1__:set',
                    'data': 'bar',
                })
            ]
        )

    def test_ignores_other_dbs(
        self, create_dummy_service, tracker, redis_db_1
    ):
        create_dummy_service(
            uri_config_key=URI_CONFIG_KEY, keys='*', events='*', dbs=0
        )
        tracker.run.reset_mock()

        redis_db_1.set('foo', 'bar')
        sleep(TIME_SLEEP)

        assert tracker.run.call_args_list == []
