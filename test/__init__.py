from unittest import TestCase


URI_CONFIG_KEY = 'TEST_KEY'
REDIS_OPTIONS = {'encoding': 'utf-8', 'decode_responses': True}


assert_items_equal = TestCase().assertCountEqual
