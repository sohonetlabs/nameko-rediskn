from unittest import TestCase

REDIS_OPTIONS = {'encoding': 'utf-8', 'decode_responses': True}
TIME_SLEEP = 0.1
URI_CONFIG_KEY = 'TEST_KEY'


assert_items_equal = TestCase().assertCountEqual
