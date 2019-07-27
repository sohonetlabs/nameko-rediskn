.PHONY: test


PACKAGE_NAME=nameko_rediskn

RABBIT_CTL_URI?=http://guest:guest@localhost:15672
AMQP_URI?=amqp://guest:guest@localhost:5672

RABBITMQ_VERSION?=3.6-management
REDIS_VERSION?=4.0


# Checks

rst-lint:
	rst-lint README.rst
	rst-lint CHANGELOG.rst

flake8:
	flake8 $(PACKAGE_NAME) test setup.py

black:
	black --check --verbose --diff .

linting: rst-lint flake8 black

# Tests

test:
	pytest test $(ARGS) \
		--rabbit-ctl-uri $(RABBIT_CTL_URI) \
		--amqp-uri $(AMQP_URI)

coverage:
	coverage run \
		--concurrency=eventlet \
		--source $(PACKAGE_NAME) \
		--branch \
		-m pytest test $(ARGS) \
		--rabbit-ctl-uri $(RABBIT_CTL_URI) \
		--amqp-uri $(AMQP_URI)
	coverage report --show-missing --fail-under 100

# Docker test containers

rabbitmq-container:
	docker run -d --rm --name rabbitmq-nameko-rediskn \
		-p 15672:15672 -p 5672:5672 \
		rabbitmq:$(RABBITMQ_VERSION)

redis-container:
	docker run -d --rm --name redis-nameko-rediskn \
		-p 6379:6379 \
		redis:$(REDIS_VERSION)
