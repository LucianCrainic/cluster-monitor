CARGO ?= cargo
BINDIR ?= $(HOME)/.local/bin
TARGET_DIR ?= target
export CARGO_TARGET_DIR := $(TARGET_DIR)

.PHONY: help install run demo test lint typecheck build binary install-bin

help:
	@echo "make demo         Run the demo from source"
	@echo "make run          Run with your configured clusters"
	@echo "make test         Run Rust tests"
	@echo "make lint         Check formatting and run Clippy"
	@echo "make build        Compile an optimized native executable"
	@echo "make install-bin  Install the executable in $(BINDIR)"

install: install-bin

run:
	$(CARGO) run --locked -- $(ARGS)

demo:
	$(CARGO) run --locked -- --demo

test:
	$(CARGO) test --locked

lint:
	$(CARGO) fmt --check
	$(CARGO) clippy --locked --all-targets -- -D warnings

typecheck:
	$(CARGO) check --locked --all-targets

build binary:
	$(CARGO) build --locked --release

install-bin: build
	install -d "$(BINDIR)"
	install -m 755 "$(TARGET_DIR)/release/cluster-monitor" "$(BINDIR)/cluster-monitor"
