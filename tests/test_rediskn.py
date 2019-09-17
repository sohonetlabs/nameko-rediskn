import logging
from unittest.mock import MagicMock, call, patch

import pytest
import eventlet
from eventlet import sleep
from nameko.exceptions import ConfigurationError

from nameko_rediskn import REDIS_PMESSAGE_TYPE
from tests import TIMEOUT, TIME_SLEEP, URI_CONFIG_KEY, assert_items_equal


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
        self, create_service, config, mock_redis_client, mock_pubsub
    ):
        event = eventlet.Event()
        mock_pubsub.listen.side_effect = event.wait
        config['REDIS']['notification_events'] = 'test_value'

        create_service(uri_config_key=URI_CONFIG_KEY, events='*', keys='*', dbs='*')
        assert mock_redis_client.config_set.call_args_list == [
            call('notify-keyspace-events', 'test_value')
        ]

    def test_does_not_use_notification_events_config_if_not_provided(
        self, create_service, config, mock_redis_client, mock_pubsub
    ):
        event = eventlet.Event()
        mock_pubsub.listen.side_effect = event.wait
        config['REDIS'].pop('notification_events')

        create_service(uri_config_key=URI_CONFIG_KEY, events='*', keys='*', dbs='*')
        assert mock_redis_client.config_set.call_args_list == []


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


class TestStopKill:
    @pytest.fixture
    def mock_thread(self):
        with patch(
            'nameko.containers.ServiceContainer.spawn_managed_thread'
        ) as spawn_managed_thread:
            yield spawn_managed_thread.return_value

    def test_container_stop(self, create_service, mock_thread):
        service = create_service(uri_config_key=URI_CONFIG_KEY, events='*')
        service.container.stop()

        assert mock_thread.kill.call_args_list == [call()]

    def test_container_kill(self, create_service, mock_thread):
        service = create_service(uri_config_key=URI_CONFIG_KEY, events='*')
        service.container.kill()

        # nameko will call `RedisKNEntrypoint.kill` twice for each `rediskn`
        # entrypoint (because it shows up both as an entrypoint and an
        # extension)
        assert mock_thread.kill.call_args_list == [call(), call()]

    @pytest.mark.parametrize('method', ['stop', 'kill'])
    def test_stop_entrypoint(self, mock_pubsub, entrypoint, method):
        event = eventlet.Event()
        mock_pubsub.listen.side_effect = event.wait
        stop_method = getattr(entrypoint, method)
        entrypoint.setup()

        with eventlet.Timeout(TIMEOUT):
            entrypoint.start()
            sleep(TIME_SLEEP)
            stop_method()

        assert entrypoint._thread.dead is True


class TestLogInformation:
    def test_log_start_listening_information(self, create_service, log_mock):
        create_service(uri_config_key=URI_CONFIG_KEY, events='*', keys='*', dbs='*')
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


def redis_listen(*side_effects):
    """Mock the redis pubsub.listen generator

    Yields the elements of `side_effects`, one at a time. If an element is an
    exception, it is raised instead of yielded. If the element is a callable,
    it is called and the return value is yielded.
    """
    for effect in side_effects:
        if (
            isinstance(effect, Exception) or
            isinstance(effect, type) and issubclass(effect, Exception)
        ):
            raise effect
        elif callable(effect):
            yield effect()
        else:
            yield effect


class TestErrorHandling:
    @pytest.fixture
    def mock_sleep(self):
        with patch('nameko_rediskn.rediskn.sleep') as m:
            yield m

    @pytest.mark.usefixtures('mock_sleep')
    def test_error_subscribing(self, mock_redis_client, entrypoint):
        mock_pubsub_1 = MagicMock()
        mock_pubsub_2 = MagicMock()
        mock_redis_client.pubsub.side_effect = [
            mock_pubsub_1,
            mock_pubsub_2
        ]
        mock_pubsub_1.psubscribe.side_effect = [None, ConnectionError('Boom!')]
        event = eventlet.Event()
        mock_pubsub_2.psubscribe.return_value = None
        mock_pubsub_2.listen.side_effect = event.wait
        entrypoint.setup()

        with eventlet.Timeout(TIMEOUT):
            entrypoint.start()
            sleep(TIME_SLEEP)
            entrypoint.stop()

        assert mock_redis_client.pubsub.call_args_list == [call(), call()]
        assert mock_pubsub_1.psubscribe.call_args_list == [
            call('__keyevent@0__:*'), call('__keyspace@0__:*')
        ]
        assert not mock_pubsub_1.listen.called
        assert mock_pubsub_2.psubscribe.call_args_list == [
            call('__keyevent@0__:*'), call('__keyspace@0__:*')
        ]
        assert mock_pubsub_2.listen.call_args_list == [call()]

    @pytest.mark.parametrize(
        'exception',
        [ConnectionError('BOOM'), TimeoutError('BOOM'), Exception('BOOM')]
    )
    @pytest.mark.usefixtures('mock_sleep')
    def test_reconnect_on_error(
        self, create_service, mock_redis_client, tracker, caplog,
        exception
    ):
        event = eventlet.Event()
        mock_pubsub_1 = MagicMock()
        mock_pubsub_2 = MagicMock()
        mock_redis_client.pubsub.side_effect = [
            mock_pubsub_1,
            mock_pubsub_2
        ]
        mock_pubsub_1.listen.side_effect = exception
        mock_pubsub_2.listen.return_value = redis_listen(
            {
                'type': 'pmessage',
                'pattern': '__keyspace@*__:*',
                'channel': '__keyspace@0__:foo',
                'data': 'expire',
            },
            event.wait
        )

        with eventlet.Timeout(TIMEOUT):
            service = create_service(uri_config_key=URI_CONFIG_KEY, events='*')
            service.container.stop()

        assert mock_redis_client.pubsub.call_args_list == [call(), call()]
        assert (
            'nameko_rediskn.rediskn', logging.ERROR,
            'Error while listening for redis keyspace notifications'
        ) in caplog.record_tuples
        assert mock_pubsub_1.listen.call_args_list == [call()]
        assert mock_pubsub_2.listen.call_args_list == [call()]
        assert tracker.call_args_list == [
            call({
                'type': 'pmessage',
                'pattern': '__keyspace@*__:*',
                'channel': '__keyspace@0__:foo',
                'data': 'expire',
            })
        ]

    @pytest.mark.parametrize(
        'backoff_factor, sleep_durations',
        [
            (0, [0, 0, 0, 0, 0]),
            (0.5, [0.5, 1.0, 2.0, 4.0, 0.5]),
            (1, [1, 2, 4, 8, 1]),
            (3, [3, 6, 12, 24, 3]),
        ]
    )
    def test_exponential_backoff_listen_error(
        self, entrypoint, config, mock_pubsub, mock_sleep, backoff_factor,
        sleep_durations
    ):
        config['REDIS'] = {'pubsub_backoff_factor': backoff_factor}
        entrypoint.setup()
        event = eventlet.Event()
        mock_pubsub.listen.side_effect = [
            ConnectionError('Error1'),
            Exception('Error2'),
            ConnectionError('Error3'),
            TimeoutError('Error4'),
            redis_listen(
                {
                    'type': 'pmessage',
                    'pattern': '__keyspace@*__:*',
                    'channel': '__keyspace@0__:foo',
                    'data': 'expire',
                },
                ConnectionError('Error5')
            ),
            redis_listen(event.wait)
        ]

        with eventlet.Timeout(TIMEOUT):
            entrypoint.start()
            sleep(TIME_SLEEP)
            entrypoint.stop()

        assert mock_sleep.call_args_list == [
            call(duration) for duration in sleep_durations
        ]

    def test_default_backoff_factor_listen_error(
        self, entrypoint, config, mock_pubsub, mock_sleep
    ):
        config['REDIS'].pop('pubsub_backoff_factor', None)
        entrypoint.setup()
        event = eventlet.Event()
        mock_pubsub.listen.side_effect = [
            ConnectionError('Error1'),
            Exception('Error2'),
            ConnectionError('Error3'),
            TimeoutError('Error4'),
            redis_listen(
                {
                    'type': 'pmessage',
                    'pattern': '__keyspace@*__:*',
                    'channel': '__keyspace@0__:foo',
                    'data': 'expire',
                },
                ConnectionError('Error5')
            ),
            redis_listen(event.wait)
        ]

        with eventlet.Timeout(TIMEOUT):
            entrypoint.start()
            sleep(TIME_SLEEP)
            entrypoint.stop()

        assert mock_sleep.call_args_list == [
            call(2),
            call(4),
            call(8),
            call(16),
            call(2),
        ]

    @pytest.mark.parametrize(
        'backoff_factor, sleep_durations',
        [
            (0, [0, 0, 0, 0]),
            (0.5, [0.5, 1.0, 2.0, 4.0]),
            (1, [1, 2, 4, 8]),
            (3, [3, 6, 12, 24]),
        ]
    )
    def test_exponential_backoff_subscribe_error(
        self, entrypoint, config, mock_pubsub, mock_sleep, backoff_factor,
        sleep_durations
    ):
        config['REDIS'] = {'pubsub_backoff_factor': backoff_factor}
        entrypoint.setup()
        event = eventlet.Event()
        mock_pubsub.psubscribe.side_effect = [
            ConnectionError('Error1'),
            Exception('Error2'),
            ConnectionError('Error3'),
            TimeoutError('Error4'),
            None, None  # Subscribes successfully
        ]
        mock_pubsub.listen.side_effect = event.wait

        with eventlet.Timeout(TIMEOUT):
            entrypoint.start()
            sleep(TIME_SLEEP)
            entrypoint.stop()

        assert mock_sleep.call_args_list == [
            call(duration) for duration in sleep_durations
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
            ],
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
            ],
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
            ],
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
            ],
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
        create_service(uri_config_key=URI_CONFIG_KEY, events='psubscribe', dbs='*')
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
            ],
        )

    @pytest.mark.parametrize('events', [['set', 'hset'], ('set', 'hset')])
    def test_listen_multiple_events(self, create_service, tracker, redis, events):
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
            ],
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
        create_service(uri_config_key=URI_CONFIG_KEY, keys='*', events='*', dbs=1)
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
        create_service(uri_config_key=URI_CONFIG_KEY, keys='*', events='*', dbs=1)

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
            ],
        )

    def test_listen_multiple_dbs(self, create_service, tracker, redis, redis_db_1):
        create_service(uri_config_key=URI_CONFIG_KEY, keys='*', events='*', dbs=[0, 1])

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
        create_service(uri_config_key=URI_CONFIG_KEY, keys='*', events='*', dbs=0)
        tracker.reset_mock()

        redis_db_1.set('foo', 'bar')
        sleep(TIME_SLEEP)

        assert tracker.call_args_list == []
