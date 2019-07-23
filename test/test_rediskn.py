from unittest.mock import call, patch, MagicMock

import pytest
from eventlet import sleep
from nameko.exceptions import ConfigurationError

from nameko_rediskn import REDIS_PMESSAGE_TYPE
from test import assert_items_equal, TIME_SLEEP, URI_CONFIG_KEY


class TestPublicConstants:

    def test_value(self):
        assert REDIS_PMESSAGE_TYPE == 'pmessage'


class TestConfig:

    def test_raises_if_uri_config_key_not_found(self, create_service, config):
        config['REDIS_URIS'] = {'WRONG_KEY': "redis://localhost:6379/0"}

        with pytest.raises(KeyError) as exc:
            create_service(
                config=config,
                uri_config_key=URI_CONFIG_KEY,
                events='*',
                keys='*',
                dbs='*',
            )

        assert exc.value.args[0] == 'TEST_KEY'

    def test_uses_notification_events_config_if_provided(
        self, create_service, config
    ):
        config['REDIS']['notification_events'] = 'test_value'

        with patch('nameko_rediskn.rediskn.StrictRedis') as strict_redis_mock:
            create_service(
                uri_config_key=URI_CONFIG_KEY, events='*', keys='*', dbs='*'
            )
            redis_mock = strict_redis_mock.from_url.return_value
            assert redis_mock.config_set.call_args_list == [
                call('notify-keyspace-events', 'test_value')
            ]

    def test_does_not_use_notification_events_config_if_not_provided(
        self, create_service, config
    ):
        config['REDIS'].pop('notification_events')

        with patch('nameko_rediskn.rediskn.StrictRedis') as strict_redis_mock:
            create_service(
                uri_config_key=URI_CONFIG_KEY, events='*', keys='*', dbs='*'
            )
            redis_mock = strict_redis_mock.from_url.return_value
            assert redis_mock.config_set.call_args_list == []


class TestSubscribeAPI:

    def test_raises_if_uri_config_key_not_supplied(self, create_service):
        with pytest.raises(TypeError):
            create_service()

        with pytest.raises(TypeError):
            create_service(events='*', keys='*', dbs=[1])

    def test_raises_if_missing_arguments(self, create_service, log_mock):
        with pytest.raises(ConfigurationError):
            create_service(uri_config_key=URI_CONFIG_KEY)

        assert log_mock.error.call_args_list == [
            call('Provide either `events` or `keys` to get notifications')
        ]
        log_mock.error.reset_mock()

        with pytest.raises(ConfigurationError):
            create_service(uri_config_key=URI_CONFIG_KEY, dbs=[1])

        assert log_mock.error.call_args_list == [
            call('Provide either `events` or `keys` to get notifications')
        ]


class TestContainerStop:

    def test_kills_thread_if_exists(self, create_service):
        with patch(
            'nameko.containers.ServiceContainer.spawn_managed_thread'
        ) as spawn_managed_thread:
            thread_mock = MagicMock()
            thread_mock.kill.return_value = MagicMock()
            spawn_managed_thread.return_value = thread_mock
            service = create_service(uri_config_key=URI_CONFIG_KEY, events='*')
            service.container.stop()

        assert thread_mock.kill.call_args_list == [call()]

        entrypoint = next(iter(service.container.entrypoints))
        assert entrypoint._thread is None
        assert entrypoint.client is None

    def test_does_not_kill_thread_if_not_exists(self, create_service):
        with patch(
            'nameko.containers.ServiceContainer.spawn_managed_thread'
        ) as spawn_managed_thread:
            thread_mock = MagicMock()
            thread_mock.kill.return_value = MagicMock()
            spawn_managed_thread.return_value = None
            service = create_service(uri_config_key=URI_CONFIG_KEY, events='*')
            service.container.stop()

        assert thread_mock.kill.call_args_list == []

        entrypoint = next(iter(service.container.entrypoints))
        assert entrypoint._thread is None
        assert entrypoint.client is None


class TestContainerKill:

    def test_kills_thread_if_exists(self, create_service):
        with patch(
            'nameko.containers.ServiceContainer.spawn_managed_thread'
        ) as spawn_managed_thread:
            thread_mock = MagicMock()
            thread_mock.kill.return_value = MagicMock()
            spawn_managed_thread.return_value = thread_mock
            service = create_service(uri_config_key=URI_CONFIG_KEY, events='*')
            service.container.kill()

        assert thread_mock.kill.call_args_list == [call()]

        entrypoint = next(iter(service.container.entrypoints))
        assert entrypoint._thread is None
        assert entrypoint.client is None

    def test_does_not_kill_thread_if_not_exists(self, create_service):
        with patch(
            'nameko.containers.ServiceContainer.spawn_managed_thread'
        ) as spawn_managed_thread:
            thread_mock = MagicMock()
            thread_mock.kill.return_value = MagicMock()
            spawn_managed_thread.return_value = None
            service = create_service(uri_config_key=URI_CONFIG_KEY, events='*')
            service.container.kill()

        assert thread_mock.kill.call_args_list == []

        entrypoint = next(iter(service.container.entrypoints))
        assert entrypoint._thread is None
        assert entrypoint.client is None


class TestLogInformation:

    def test_log_start_listening_information(self, create_service, log_mock):
        create_service(
            uri_config_key=URI_CONFIG_KEY, events='*', keys='*', dbs='*'
        )
        assert log_mock.info.call_args_list == [
            call('Started listening to Redis keyspace notifications')
        ]

    def test_log_stop_listening_information(self, create_service, log_mock):
        service = create_service(
            uri_config_key=URI_CONFIG_KEY, events='*', keys='*', dbs='*'
        )
        log_mock.info.reset_mock()

        service.container.kill()

        assert log_mock.info.call_args_list == [
            call('Stopped listening to Redis keyspace notifications')
        ]


class TestListenAll:

    @pytest.fixture
    def service(self, create_service):
        return create_service(
            uri_config_key=URI_CONFIG_KEY, events='*', keys='*', dbs='*'
        )

    @pytest.mark.usefixtures('service')
    def test_subscribe_events(self, tracker):
        assert_items_equal(
            tracker.call_args_list,
            [
                call(
                    {
                        'type': 'psubscribe',
                        'pattern': None,
                        'channel': '__keyevent@*__:*',
                        'data': 1,
                    }
                ),
                call(
                    {
                        'type': 'psubscribe',
                        'pattern': None,
                        'channel': '__keyspace@*__:*',
                        'data': 2,
                    }
                ),
            ]
        )

    @pytest.mark.parametrize(
        'action, args, event_type',
        [
            ('set', ('foo', 'bar'), 'set'),
            ('hset', ('foo', 'bar', 'baz'), 'hset'),
            ('hmset', ('foo', {'bar': 'baz'}), 'hset'),
        ],
    )
    @pytest.mark.usefixtures('service')
    def test_simple_events(self, tracker, redis, action, args, event_type):
        method = getattr(redis, action)
        method(*args)
        sleep(TIME_SLEEP)

        key = args[0]

        assert_items_equal(
            tracker.call_args_list,
            [
                call(
                    {
                        'type': 'psubscribe',
                        'pattern': None,
                        'channel': '__keyevent@*__:*',
                        'data': 1,
                    }
                ),
                call(
                    {
                        'type': 'psubscribe',
                        'pattern': None,
                        'channel': '__keyspace@*__:*',
                        'data': 2,
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyspace@*__:*',
                        'channel': '__keyspace@0__:{}'.format(key),
                        'data': event_type,
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyevent@*__:*',
                        'channel': '__keyevent@0__:{}'.format(event_type),
                        'data': key,
                    }
                ),
            ]
        )

    @pytest.mark.usefixtures('service')
    def test_del(self, tracker, redis):
        redis.set('foo', 'bar')
        redis.delete('foo')
        sleep(TIME_SLEEP)

        assert_items_equal(
            tracker.call_args_list,
            [
                call(
                    {
                        'type': 'psubscribe',
                        'pattern': None,
                        'channel': '__keyevent@*__:*',
                        'data': 1,
                    }
                ),
                call(
                    {
                        'type': 'psubscribe',
                        'pattern': None,
                        'channel': '__keyspace@*__:*',
                        'data': 2,
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyspace@*__:*',
                        'channel': '__keyspace@0__:foo',
                        'data': 'set',
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyevent@*__:*',
                        'channel': '__keyevent@0__:set',
                        'data': 'foo',
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyspace@*__:*',
                        'channel': '__keyspace@0__:foo',
                        'data': 'del',
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyevent@*__:*',
                        'channel': '__keyevent@0__:del',
                        'data': 'foo',
                    }
                ),
            ]
        )

    @pytest.mark.parametrize('keys', [('one',), ('one', 'two')])
    @pytest.mark.usefixtures('service')
    def test_hdel(self, tracker, redis, keys):
        redis.hmset('foo', {'one': '1', 'two': '2', 'three': '3'})
        redis.hdel('foo', *keys)
        sleep(TIME_SLEEP)

        assert_items_equal(
            tracker.call_args_list,
            [
                call(
                    {
                        'type': 'psubscribe',
                        'pattern': None,
                        'channel': '__keyevent@*__:*',
                        'data': 1,
                    }
                ),
                call(
                    {
                        'type': 'psubscribe',
                        'pattern': None,
                        'channel': '__keyspace@*__:*',
                        'data': 2,
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyspace@*__:*',
                        'channel': '__keyspace@0__:foo',
                        'data': 'hset',
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyevent@*__:*',
                        'channel': '__keyevent@0__:hset',
                        'data': 'foo',
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyspace@*__:*',
                        'channel': '__keyspace@0__:foo',
                        'data': 'hdel',
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyevent@*__:*',
                        'channel': '__keyevent@0__:hdel',
                        'data': 'foo',
                    }
                ),
            ]
        )

    @pytest.mark.parametrize(
        'action, ttl, wait_time', [('expire', 1, 1.1), ('pexpire', 1000, 1.1)]
    )
    @pytest.mark.usefixtures('service')
    def test_expire(self, tracker, redis, action, ttl, wait_time):
        redis.set('foo', 'bar')
        method = getattr(redis, action)
        method('foo', ttl)

        sleep(TIME_SLEEP)

        call_args_list = [
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyevent@*__:*',
                    'data': 1,
                }
            ),
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyspace@*__:*',
                    'data': 2,
                }
            ),
            call(
                {
                    'type': 'pmessage',
                    'pattern': '__keyspace@*__:*',
                    'channel': '__keyspace@0__:foo',
                    'data': 'set',
                }
            ),
            call(
                {
                    'type': 'pmessage',
                    'pattern': '__keyevent@*__:*',
                    'channel': '__keyevent@0__:set',
                    'data': 'foo',
                }
            ),
            call(
                {
                    'type': 'pmessage',
                    'pattern': '__keyspace@*__:*',
                    'channel': '__keyspace@0__:foo',
                    'data': 'expire',
                }
            ),
            call(
                {
                    'type': 'pmessage',
                    'pattern': '__keyevent@*__:*',
                    'channel': '__keyevent@0__:expire',
                    'data': 'foo',
                }
            ),
        ]
        assert_items_equal(tracker.call_args_list, call_args_list)

        sleep(wait_time)

        call_args_list.extend(
            [
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyspace@*__:*',
                        'channel': '__keyspace@0__:foo',
                        'data': 'expired',
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyevent@*__:*',
                        'channel': '__keyevent@0__:expired',
                        'data': 'foo',
                    }
                ),
            ]
        )
        assert_items_equal(tracker.call_args_list, call_args_list)


class TestListenEvents:

    def test_subscribe_events(self, create_service, tracker):
        create_service(
            uri_config_key=URI_CONFIG_KEY, events='psubscribe', dbs='*'
        )
        assert tracker.call_args_list == [
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyevent@*__:psubscribe',
                    'data': 1,
                }
            )
        ]

    def test_listen_event(self, create_service, tracker, redis):
        create_service(uri_config_key=URI_CONFIG_KEY, events='set', dbs='*')

        redis.set('foo', 'bar')
        sleep(TIME_SLEEP)

        assert_items_equal(
            tracker.call_args_list,
            [
                call(
                    {
                        'type': 'psubscribe',
                        'pattern': None,
                        'channel': '__keyevent@*__:set',
                        'data': 1,
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyevent@*__:set',
                        'channel': '__keyevent@0__:set',
                        'data': 'foo',
                    }
                ),
            ]
        )

    @pytest.mark.parametrize('events', [['set', 'hset'], ('set', 'hset')])
    def test_listen_multiple_events(
        self, create_service, tracker, redis, events
    ):
        create_service(uri_config_key=URI_CONFIG_KEY, events=events, dbs='*')

        redis.set('foo', 'bar')
        sleep(TIME_SLEEP)

        call_args_list = [
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyevent@*__:set',
                    'data': 1,
                }
            ),
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyevent@*__:hset',
                    'data': 2,
                }
            ),
            call(
                {
                    'type': 'pmessage',
                    'pattern': '__keyevent@*__:set',
                    'channel': '__keyevent@0__:set',
                    'data': 'foo',
                }
            ),
        ]
        assert_items_equal(tracker.call_args_list, call_args_list)

        redis.hset('one', 'two', 'three')
        sleep(TIME_SLEEP)

        call_args_list.append(
            call(
                {
                    'type': 'pmessage',
                    'pattern': '__keyevent@*__:hset',
                    'channel': '__keyevent@0__:hset',
                    'data': 'one',
                }
            )
        )
        assert_items_equal(tracker.call_args_list, call_args_list)

    def test_ignores_other_events(self, create_service, tracker, redis):
        create_service(uri_config_key=URI_CONFIG_KEY, events='hset', dbs='*')
        tracker.reset_mock()

        redis.set('foo', 'bar')
        sleep(TIME_SLEEP)

        assert tracker.call_args_list == []


class TestListenKeys:

    def test_subscribe_events(self, create_service, tracker):
        create_service(uri_config_key=URI_CONFIG_KEY, keys='foo', dbs='*')
        assert tracker.call_args_list == [
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyspace@*__:foo',
                    'data': 1,
                }
            )
        ]

    def test_listen_key(self, create_service, tracker, redis):
        create_service(uri_config_key=URI_CONFIG_KEY, keys='foo', dbs='*')

        redis.set('foo', 'bar')
        sleep(TIME_SLEEP)

        assert_items_equal(
            tracker.call_args_list,
            [
                call(
                    {
                        'type': 'psubscribe',
                        'pattern': None,
                        'channel': '__keyspace@*__:foo',
                        'data': 1,
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyspace@*__:foo',
                        'channel': '__keyspace@0__:foo',
                        'data': 'set',
                    }
                ),
            ]
        )

    @pytest.mark.parametrize('keys', [['foo', 'bar'], ('foo', 'bar')])
    def test_listen_multiple_keys(self, create_service, tracker, redis, keys):
        create_service(uri_config_key=URI_CONFIG_KEY, keys=keys, dbs='*')

        redis.set('foo', '1')
        sleep(TIME_SLEEP)

        call_args_list = [
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyspace@*__:foo',
                    'data': 1,
                }
            ),
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyspace@*__:bar',
                    'data': 2,
                }
            ),
            call(
                {
                    'type': 'pmessage',
                    'pattern': '__keyspace@*__:foo',
                    'channel': '__keyspace@0__:foo',
                    'data': 'set',
                }
            ),
        ]
        assert_items_equal(tracker.call_args_list, call_args_list)

        redis.set('bar', '2')
        sleep(TIME_SLEEP)

        call_args_list.extend(
            [
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyspace@*__:bar',
                        'channel': '__keyspace@0__:bar',
                        'data': 'set',
                    }
                )
            ]
        )
        assert_items_equal(tracker.call_args_list, call_args_list)

    def test_ignores_other_keys(self, create_service, tracker, redis):
        create_service(uri_config_key=URI_CONFIG_KEY, keys='foo', dbs='*')
        tracker.reset_mock()

        redis.set('bar', '2')
        sleep(TIME_SLEEP)

        assert tracker.call_args_list == []


class TestListenDB:

    def test_subscribes_to_db_from_uri(self, create_service, tracker):
        create_service(uri_config_key=URI_CONFIG_KEY, keys='*', events='*')
        assert tracker.call_args_list == [
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyevent@0__:*',
                    'data': 1,
                }
            ),
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyspace@0__:*',
                    'data': 2,
                }
            ),
        ]

    def test_subscribe_events(self, create_service, tracker):
        create_service(
            uri_config_key=URI_CONFIG_KEY, keys='*', events='*', dbs=1
        )
        assert tracker.call_args_list == [
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyevent@1__:*',
                    'data': 1,
                }
            ),
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyspace@1__:*',
                    'data': 2,
                }
            ),
        ]

    def test_listen_db(self, create_service, tracker, redis_db_1):
        create_service(
            uri_config_key=URI_CONFIG_KEY, keys='*', events='*', dbs=1
        )

        redis_db_1.set('foo', 'bar')
        sleep(TIME_SLEEP)

        assert_items_equal(
            tracker.call_args_list,
            [
                call(
                    {
                        'type': 'psubscribe',
                        'pattern': None,
                        'channel': '__keyevent@1__:*',
                        'data': 1,
                    }
                ),
                call(
                    {
                        'type': 'psubscribe',
                        'pattern': None,
                        'channel': '__keyspace@1__:*',
                        'data': 2,
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyspace@1__:*',
                        'channel': '__keyspace@1__:foo',
                        'data': 'set',
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyevent@1__:*',
                        'channel': '__keyevent@1__:set',
                        'data': 'foo',
                    }
                ),
            ]
        )

    def test_listen_multiple_dbs(
        self, create_service, tracker, redis, redis_db_1
    ):
        create_service(
            uri_config_key=URI_CONFIG_KEY, keys='*', events='*', dbs=[0, 1]
        )

        redis.set('foo', '1')
        sleep(TIME_SLEEP)

        call_args_list = [
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyevent@0__:*',
                    'data': 1,
                }
            ),
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyevent@1__:*',
                    'data': 2,
                }
            ),
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyspace@0__:*',
                    'data': 3,
                }
            ),
            call(
                {
                    'type': 'psubscribe',
                    'pattern': None,
                    'channel': '__keyspace@1__:*',
                    'data': 4,
                }
            ),
            call(
                {
                    'type': 'pmessage',
                    'pattern': '__keyspace@0__:*',
                    'channel': '__keyspace@0__:foo',
                    'data': 'set',
                }
            ),
            call(
                {
                    'type': 'pmessage',
                    'pattern': '__keyevent@0__:*',
                    'channel': '__keyevent@0__:set',
                    'data': 'foo',
                }
            ),
        ]
        assert_items_equal(tracker.call_args_list, call_args_list)

        redis_db_1.set('bar', '2')
        sleep(TIME_SLEEP)

        call_args_list.extend(
            [
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyspace@1__:*',
                        'channel': '__keyspace@1__:bar',
                        'data': 'set',
                    }
                ),
                call(
                    {
                        'type': 'pmessage',
                        'pattern': '__keyevent@1__:*',
                        'channel': '__keyevent@1__:set',
                        'data': 'bar',
                    }
                ),
            ]
        )
        assert_items_equal(tracker.call_args_list, call_args_list)

    def test_ignores_other_dbs(self, create_service, tracker, redis_db_1):
        create_service(
            uri_config_key=URI_CONFIG_KEY, keys='*', events='*', dbs=0
        )
        tracker.reset_mock()

        redis_db_1.set('foo', 'bar')
        sleep(TIME_SLEEP)

        assert tracker.call_args_list == []
