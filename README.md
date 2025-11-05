# Slonyara

Utilities for structured logging across the project.

## Quick start

1. **Create a virtual environment and install dependencies.**

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   make install
   ```

   > [!TIP]
   > Windows environments often lack GNU Make. If `make install` is not
   > available, run the equivalent pip command instead:
   >
   > ```powershell
   > python -m pip install --upgrade pip
   > python -m pip install -r requirements.txt
   > ```

   > [!NOTE]
   > When using **Python 3.13 on Windows**, installing `pydantic-core`
   > requires native compilation. Ensure both the Rust toolchain and the
   > *Microsoft C++ Build Tools* (which provide `link.exe`) are installed and
   > available in `PATH` before running the `pip install` command. If setting
   > up the build tools is not an option, install Python 3.12 where pre-built
   > wheels are still distributed.

2. **Configure the bot token and runtime options.**

   The project reads configuration values from a `.env` file. An example
   file is already provided with a development token, default storage
   location and reminder timing.

   ```bash
   cat .env
   ```

   Update the values if necessary, or replace them with your production
   credentials before deployment.

3. **Apply database migrations.**

   ```bash
   python -m slonyara migrate
   ```

   The command initialises the SQLite database (the default location is
   `data/meetings.db`) and ensures the latest schema version is applied.

4. **Launch the bot.**

   ```bash
   make run
   ```

   The command loads environment variables from `.env`, runs migrations
   implicitly if needed, and starts polling updates from Telegram using
   the same entry point as `python -m slonyara run`. You can omit the
   sub-command and simply run `python -m slonyara` to start the bot with
   the default `run` action.

## Architecture

The [architecture overview](docs/architecture.md) describes the layered
design of the bot, infrastructure components (such as the centralized
`TelegramSender` queue), the click-guard workflow, and the logging and
metrics conventions used throughout the project.
