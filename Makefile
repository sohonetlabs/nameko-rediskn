PACKAGE_NAME=nameko_rediskn
TESTS_PACKAGE_NAME=tests

RABBIT_CTL_URI?=http://guest:guest@localhost:15672
AMQP_URI?=amqp://guest:guest@localhost:5672

RABBITMQ_VERSION?=3.6-management
REDIS_VERSION?=4.0


# Checks

rst-lint:
	rst-lint README.rst
	rst-lint CHANGELOG.rst

flake8:
	flake8 src/$(PACKAGE_NAME) $(TESTS_PACKAGE_NAME) setup.py

black:
	black --check --verbose --diff .

isort:
	isort --recursive --check-only --diff

linting: rst-lint flake8 black isort

# Tests

test:
	pytest $(TESTS_PACKAGE_NAME) $(ARGS) \
		--rabbit-ctl-uri $(RABBIT_CTL_URI) \
		--amqp-uri $(AMQP_URI)

coverage:
	coverage run \
		--concurrency=eventlet \
		--source $(PACKAGE_NAME) \
		--branch \
		-m pytest $(TESTS_PACKAGE_NAME) $(ARGS) \
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
